"""
training
quantizing in each convolution
use preloaded weights

"""
import os
from datetime import datetime as dt
import numpy as np
import tensorflow as tf
from keras.datasets import cifar100
import scipy.io


weights_raw = scipy.io.loadmat('sqz_full.mat')
# for name in weights_raw:
#     print(name)
# exit()
def float_quant(x): 
    t = tf.fill(tf.shape(x), 21)
    t1 = tf.cast(t, tf.int32)
    a = tf.fill(tf.shape(x), 0x100000)
    inp = tf.bitcast(x, tf.int32)
    inp = inp+a
    x_q = tf.bitcast(tf.bitwise.left_shift(tf.bitwise.right_shift(inp, t), t), tf.float32)
    return x# + tf.stop_gradient(x_q - x)

# define squeeze module
def squeeze(input, channels, layer_num, trainable ):
    """
    Defines squeezed block for fire module.

    :param input: input tensor
    :param channels: number of output channels
    :param layer_num: layer number for naming purposes
    :return: output tensor convoluted with squeeze layer
    """
    layer_name = 'squeeze_' + str(layer_num)
    nm = 'fire'+str(layer_num)+'/squeeze1x1'
    wei,bia=weights_raw[nm][0]
    input_channels = input.get_shape().as_list()[3]

    with tf.name_scope(layer_name):
        weights = float_quant(tf.Variable(wei,name='weight', trainable=trainable))
        biases = float_quant(tf.Variable(bia, name='biases'))
        onebyone = tf.nn.conv2d(input, weights, strides=(1, 1, 1, 1), padding='VALID') + biases
        A = tf.nn.relu(onebyone)

        tf.summary.histogram('weights', weights)
        tf.summary.histogram('biases', biases)
        tf.summary.histogram('logits', onebyone)
        tf.summary.histogram('activations', A)

    return A

# define expand module
def expand(input, channels_1by1, channels_3by3, layer_num, trainable):
    """
    Defines expand block for fire module.
    :param input: input tensor
    :param channels_1by1: number of output channels in 1x1 layers
    :param channels_3by3: number of output channels in 3x3 layers
    :param layer_num: layer number for naming purposes
    :return: output tensor convoluted with expand layer
    """

    layer_name = 'expand_' + str(layer_num)
    input_channels = input.get_shape().as_list()[3]
    nm = 'fire'+str(layer_num)+'/expand1x1'
    wei,bia=weights_raw[nm][0]
    nm = 'fire'+str(layer_num)+'/expand3x3'
    wei3,bia3=weights_raw[nm][0]

    with tf.name_scope(layer_name):
        weights1x1 = float_quant(tf.Variable(wei,name= 'weight', trainable=trainable))
        biases1x1 = float_quant(tf.Variable(bia, name='biases', trainable=trainable))
        onebyone = tf.nn.conv2d(input, weights1x1, strides=(1, 1, 1, 1), padding='VALID') + biases1x1
        A_1x1 = tf.nn.relu(onebyone)

        tf.summary.histogram('weights_1x1', weights1x1)
        tf.summary.histogram('biases_1x1', biases1x1)
        tf.summary.histogram('logits_1x1', onebyone)
        tf.summary.histogram('activations_1x1', A_1x1)

        weights3x3 = float_quant(tf.Variable(wei3, name='weight', trainable=trainable))
        biases3x3 = float_quant(tf.Variable(bia3, name='biases', trainable=trainable))
        threebythree = tf.nn.conv2d(input, weights3x3, strides=(1, 1, 1, 1), padding='SAME') + biases3x3
        A_3x3 = tf.nn.relu(threebythree)

        tf.summary.histogram('weights_3x3', weights3x3)
        tf.summary.histogram('biases_3x3', biases3x3)
        tf.summary.histogram('logits_3x3', threebythree)
        tf.summary.histogram('activations_3x3', A_3x3)

    return tf.concat([A_1x1, A_3x3], axis=3)


# define fire module
def fire_module(input, squeeze_channels, expand_channels_1by1, expand_channels_3by3, layer_num, trainable=True):
    """
    Train fire module. Fire module does not change input height and width, only depth.
    :param input: input tensor
    :param squeeze_channels: number of channels for 1x1 squeeze layer
    :param expand_channels_1by1: number of channels for 1x1 expand layer
    :param expand_channels_3by3: number of channels for 3x3 expand layer
    :param layer_num: number of layer for naming purposes only
    :return: a tensor of shape [input_height x input_width x expand_channels_1by1 * expand_channels_3by3]
    """
    with tf.name_scope('fire_' + str(layer_num)):
        squeeze_output = squeeze(input, squeeze_channels, layer_num, trainable)
        return expand(squeeze_output, expand_channels_1by1, expand_channels_3by3, layer_num, trainable)


def model(input_height, input_width, input_channels, output_classes, pooling_size=(1, 3, 3, 1)):
    """
    Define tensorflow graph.
    :param input_height: input image height
    :param input_width: input image width
    :param input_channels: input image channels
    :param output_classes: number of output classes
    :param pooling_size: size of the pooling
    :return: list of input placeholders and output operations
    """
    with tf.Graph().as_default() as graph:
    # define placeholders
        input_image = tf.placeholder(tf.float32,
                                     shape=[None, input_height, input_width, input_channels],
                                     name='input_image')
        labels = tf.placeholder(tf.int32, shape=[None, 1])
        in_training = tf.placeholder(tf.bool, shape=())
        batch = tf.Variable(0, dtype=tf.int32)   
        learning_rate = tf.train.exponential_decay(
              0.001,                # Base learning rate.
              batch * 128,  # Current index into the dataset.
              10000,          # Decay step.
              0.95,                # Decay rate.
        staircase=True)

        tf.summary.image('input image', input_image)
    # define structure of the net
    # layer 1 - conv 1
        with tf.name_scope('conv_1'):
            wei,bia=weights_raw['conv1'][0]
            tmp0 = np.array(wei[:,:,0,:])
            tmp1 = np.array(wei[:,:,2,:])
            wei[:,:,2,:] = tmp0
            wei[:,:,0,:] = tmp1
            W_conv1 = float_quant(tf.Variable(wei, trainable=False))
            b_conv1 = float_quant(tf.Variable(bia, trainable=False))

            X_1 = tf.nn.conv2d(input_image, W_conv1, strides=(1, 2, 2, 1), padding='VALID') + b_conv1
            A_1 = tf.nn.relu(X_1)
            tf.summary.histogram('conv1 weights', W_conv1)
            tf.summary.histogram('conv1 biases', b_conv1)
            tf.summary.histogram('conv1 logits', X_1)
            tf.summary.histogram('conv1 activations', A_1)

        # layer 2 - maxpool
        maxpool_1 = tf.nn.max_pool(A_1, ksize=pooling_size, strides=(1, 2, 2, 1), padding='VALID', name='maxpool_1')

        # layer 3-5 - fire modules
        fire_2 = fire_module(maxpool_1, 16, 64, 64, layer_num=2, trainable=False)
        fire_3 = fire_module(fire_2, 16, 64, 64, layer_num=3, trainable=False)

        maxpool_4 = tf.nn.max_pool(fire_3, ksize=pooling_size, strides=(1, 2, 2, 1), padding='VALID', name='maxpool_4')
        fire_4 = fire_module(maxpool_4, 32, 128, 128, layer_num=4, trainable=False)
        fire_5 = fire_module(fire_4, 32, 128, 128, layer_num=5, trainable=False)

        maxpool_8 = tf.nn.max_pool(fire_5, ksize=pooling_size, strides=(1, 2, 2, 1), padding='VALID', name='maxpool_8')

        # layer 7-10 - fire modules
        fire_6 = fire_module(maxpool_8, 48, 192, 192, layer_num=6)
        fire_7 = fire_module(fire_6, 48, 192, 192, layer_num=7)
        fire_8 = fire_module(fire_7, 64, 256, 256, layer_num=8)
        fire_9 = fire_module(fire_8, 64, 256, 256, layer_num=9)


        dropout_9 = tf.cond(in_training,
                            lambda: tf.nn.dropout(fire_9, keep_prob=0.5),
                            lambda: fire_9)

        # layer 13 - final
        with tf.name_scope('final'):
            W_conv10 = float_quant(tf.Variable(tf.contrib.layers.xavier_initializer()([1, 1, 512, output_classes])))
            b_conv10 = float_quant(tf.Variable(tf.zeros([1, 1, 1, output_classes])))
            conv_10 = tf.nn.conv2d(dropout_9, W_conv10, strides=(1, 1, 1,1), padding='VALID') + b_conv10
            A_conv_10 = tf.nn.relu(conv_10)

            tf.summary.histogram('conv10 weights', W_conv10)
            tf.summary.histogram('conv10 biases', b_conv10)
            tf.summary.histogram('conv10 logits', conv_10)
            tf.summary.histogram('conv10 activations', A_conv_10)

        # avg pooling to get [1 x 1 x num_classes] must average over entire window oh H x W from input layer
        _, H_last, W_last, _ = A_conv_10.get_shape().as_list()
        pooled = tf.nn.avg_pool(A_conv_10, ksize=(1, H_last, W_last, 1), strides=(1, 1, 1, 1), padding='VALID')
        logits = tf.squeeze(pooled, axis=[1, 2])

        # loss + optimizer
        one_hot_labels = tf.one_hot(labels, output_classes, name='one_hot_encoding')
        loss = tf.reduce_mean(tf.nn.softmax_cross_entropy_with_logits(labels=one_hot_labels, logits=logits))
        tf.summary.scalar('loss', loss)
        optimizer = tf.train.AdamOptimizer(learning_rate).minimize(loss)

        # accuracy
        predictions = tf.reshape(tf.argmax(tf.nn.softmax(logits), axis=1, output_type=tf.int32), [-1, 1])
        accuracy = tf.reduce_mean(tf.cast(tf.equal(predictions, labels), dtype=tf.float32))
        tf.summary.scalar('train_accuracy', accuracy)

        summaries = tf.summary.merge_all()
        test_accuracy_summary = tf.summary.scalar('test_accuracy', accuracy)

    return (graph, input_image, labels, in_training, batch,learning_rate,
            loss, accuracy, summaries, test_accuracy_summary, optimizer)


def next_experiment_dir(top_dir):
    """We need directory with consecutive subdirectories to store results of consecutive trainings. """
    dirs = [int(dirname) for dirname in os.listdir(top_dir) if os.path.isdir(os.path.join(top_dir, dirname))]
    if len(dirs) > 0:
        return os.path.join(top_dir, str(max(dirs) + 1))
    else:
        return os.path.join(top_dir, '1')


def prepare_input(data, mu=None, sigma=None):
    """
    Normalizes pixels across dataset. For training set, calculate mu and sigma. For test set, transfer these
    from training set.

    :param data: dataset
    :param mu: mean pixel value across dataset. Calculated if not provided.
    :param sigma: standard deviation of pixel value across dataset. Calculated if not provided.
    :return: normalized dataset, mean and standard deviation
    """
    if mu is None:
        mu = np.mean(data)
    if sigma is None:
        sigma = np.std(data)
    data = data - mu
    data = data / sigma
    return data, mu, sigma


def run(iterations, minibatch_size):
    # ImageNet
    # input_height = input_width = 227
    # input_channels = 3
    # output_classes = 10
    # CIFAR10
    input_height = input_width = 32
    input_channels = 3
    output_classes = 100

    (x_train, y_train), (x_test, y_test) = cifar100.load_data()
    x_train, mu_train, sigma_train = prepare_input(x_train)
    x_test, _, _ = prepare_input(x_test, mu_train, sigma_train)
    train_samples = x_train.shape[0]

    (graph, input_batch, labels, in_training, batch,learning_rate,
     loss, accuracy, summaries, test_accuracy_summary, optimizer) = \
        model(input_height, input_width, input_channels, output_classes, (1, 3, 3, 1))

    with tf.Session(graph=graph,config=tf.ConfigProto(intra_op_parallelism_threads=16)) as sess:
        sess.run(tf.global_variables_initializer())

        experiment_dir = next_experiment_dir('./tmp/squeezenet')
        print("Creating output dir:", experiment_dir)
        train_writer = tf.summary.FileWriter(experiment_dir, sess.graph)

        for i in range(iterations):
            # pick random minibatch
            mb_start = np.random.randint(0, train_samples - minibatch_size)
            mb_end = mb_start + minibatch_size
            mb_data = x_train[mb_start:mb_end, :, :, :]
            mb_labels = y_train[mb_start:mb_end, :]

            feed_dict = {
                input_batch: mb_data,
                labels: mb_labels,
                in_training: True,
                batch: i
            }

            collectibles = [loss, accuracy, summaries, optimizer]

            loss_val, accuracy_val, s, _ = sess.run(collectibles, feed_dict=feed_dict)

            train_writer.add_summary(s, i)

            if i % 100 == 0:
                feed_dict = {
                    input_batch: x_test,
                    labels: y_test,
                    in_training: False,
                    batch: i
                }
                test_acc, sum_acc,lr = sess.run([accuracy, test_accuracy_summary,learning_rate], feed_dict=feed_dict)
                train_writer.add_summary(sum_acc, i)
                print('Iteration: {} \tlr {}\t loss: {:.3f}\t accuracy: {:.3f}\t test accuracy: {:.3f}'.format(
                    i,lr, loss_val, accuracy_val, test_acc))

start = dt.now()
run(10001, 128)
print('running time:', dt.now() - start)


# define session
# for n steps
#   create minibatch
#   run training step
#   run validation step
#   write results to output

# run testing summary
# print results
# bonus: save trained model

