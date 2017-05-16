from __future__ import division
import os
import time
import math
from glob import glob
import tensorflow as tf
import numpy as np

from ops import *
from datasets import *

class Finn(object):
    def __init__(self, sess, df_dim, batch_size, dropout_prob, writer_path, video_path):
        self.df_dim = df_dim
        self.batch_size = batch_size
        self.dropout_prob = dropout_prob

        self.sess = sess
        self.writer_path = writer_path
        self.filename = 'yomama'
        self.video_path = video_path


        data = generateDataSet(self.video_path)
        self.train_doublets = data["train_doublets"]
        self.train_triplets = data["train_triplets"]
        self.val_doublets = data["val_doublets"]
        self.val_targets = data["val_targets"]

        self.input_height = self.train_doublets.shape[1]
        self.input_width = self.train_doublets.shape[2]
        self.dataset_name = 'abc'

        self.gen_layer_depths = [16, 32, 64, 128]
        self.gen_filter_sizes = [3, 3, 3, 3]

    def discriminator(self, triplet, phase, reuse = False):
        with tf.variable_scope("discriminator") as scope:
            if reuse:
                scope.reuse_variables()

            h0 = lrelu(conv2d(triplet, self.df_dim, name="d_h0_conv"))
            h1 = lrelu(bn(conv2d(h0, self.df_dim*2, name="d_h1_conv"), phase, name="d_h1_bn"))
            h2 = lrelu(bn(conv2d(h1, self.df_dim*4, name="d_h2_conv"), phase, name="d_h2_bn"))
            h3 = lrelu(bn(conv2d(h2, self.df_dim*8, name="d_h3_conv"), phase, name="d_h3_bn"))
            h4 = linear(tf.reshape(h3, [self.batch_size, -1]), 1, 'd_h3_lin')

            return tf.nn.sigmoid(h4), h4

    def generator(self, doublet):
        with tf.variable_scope("generator"):
            conv_outputs = []

            current_input = doublet
            current_inputdepth = doublet.shape[3]
            for i, outputdepth in enumerate(self.gen_layer_depths):
                result = conv_block(current_input, self.is_training, self.gen_filter_sizes[i], outputdepth, name=('g_conv_block'+str(i)) )
                conv_outputs.append(result)
                current_input = result
                current_inputdepth = outputdepth

            z = current_input

            rev_layer_depths = list(reversed(self.gen_layer_depths))
            rev_filter_sizes = list(reversed(self.gen_filter_sizes))
            rev_conv_outputs = list(reversed(conv_outputs))

            # deconv portion
            for i, outputdepth in enumerate(rev_layer_depths[1:]): # reverse process exactly until last step
                result = deconv_block(current_input, self.is_training, rev_filter_sizes[i], outputdepth, name=('g_deconv_block'+str(i)) )
                if i <= 4:
                    result = tf.nn.dropout(result, self.dropout_prob)
                print( i, result.get_shape() )
                stack = tf.concat([result, rev_conv_outputs[i+1]], 3)
                print( i, stack.get_shape() )
                current_input = stack

            outputdepth = 3 # final image is 3 channel
            return tanh_deconv_block(current_input, self.is_training, rev_filter_sizes[-1], outputdepth, name=('g_tanh_deconv') )


    def build_model(self):
        image_dims = [self.input_height, self.input_width, 6]
        triplet_dims = [self.input_height, self.input_width, 9]

        self.doublets = tf.placeholder(tf.float32, [self.batch_size] + image_dims, name = 'real_images')
        self.triplets = tf.placeholder(tf.float32, [self.batch_size] + triplet_dims, name = 'real_images')
        self.is_training = tf.placeholder(tf.bool, (), name = 'is_training')

        self.G = self.generator(self.doublets)
        self.D_real, self.D_real_logits = self.discriminator(self.triplets, self.is_training, reuse=False)

        self.before, self.after = tf.split(self.doublets, [3, 3], 3)
        self.fake_triplets = tf.concat([self.before, self.G, self.after], 3)

        self.D_fake, self.D_fake_logits = self.discriminator(self.fake_triplets, self.is_training, reuse=True)

        self.d_real_sum = tf.summary.histogram("d_real", self.D_real)
        self.d_fake_sum = tf.summary.histogram("d_fake", self.D_fake)
        self.num_images = self.batch_size
        self.G_image = tf.summary.image("G", self.G, max_outputs=self.num_images)
        self.before_image = tf.summary.image("Z1", self.before, max_outputs=self.num_images)
        self.after_image = tf.summary.image("Z2", self.after, max_outputs=self.num_images)

        self.d_loss_real = tf.reduce_mean(
            tf.nn.sigmoid_cross_entropy_with_logits(logits=self.D_real_logits, labels=tf.ones_like(self.D_real)))
        self.d_loss_fake = tf.reduce_mean(
            tf.nn.sigmoid_cross_entropy_with_logits(logits=self.D_fake_logits, labels=tf.zeros_like(self.D_fake)))
        self.g_loss = tf.reduce_mean(
            tf.nn.sigmoid_cross_entropy_with_logits(logits=self.D_fake_logits, labels=tf.ones_like(self.D_fake)))

        self.d_loss_sum_real = tf.summary.scalar("real_loss", self.d_loss_real)
        self.d_loss_sum_fake = tf.summary.scalar("fake_loss", self.d_loss_fake)

        self.d_loss = self.d_loss_fake + self.d_loss_real

        self.g_loss_sum = tf.summary.scalar("G_loss", self.g_loss)
        self.d_loss_sum = tf.summary.scalar("D_loss", self.d_loss)

        t_vars = tf.trainable_variables()

        self.d_vars = [var for var in t_vars if 'd_' in var.name]
        self.g_vars = [var for var in t_vars if 'g_' in var.name]
        print(self.g_vars)
        self.saver = tf.train.Saver()

    def train(self, config):
        g_optim = tf.train.AdamOptimizer(config.learning_rate, beta1=config.beta1
                                         ).minimize(-self.d_loss_fake, var_list=self.g_vars)
        d_optim = tf.train.AdamOptimizer(0.3*config.learning_rate, beta1=config.beta1
                                                    ).minimize(self.d_loss, var_list=self.d_vars)

        tf.global_variables_initializer().run()

        self.g_sum = tf.summary.merge([self.g_loss_sum, self.d_loss_sum_fake, self.d_fake_sum])
        self.d_sum = tf.summary.merge([self.d_loss_sum_real, self.d_real_sum, self.d_loss_sum])
        self.img_sum = tf.summary.merge([self.G_image, self.before_image, self.after_image])
        self.writer = tf.summary.FileWriter(self.writer_path + "/" + self.filename, self.sess.graph)


        train_doublets = self.train_doublets
        train_triplets = self.train_triplets
        val_doublets = self.val_doublets
        val_targets = self.val_targets

        train_triplets_idx = np.arange(train_triplets.shape[0])
        np.random.shuffle(train_triplets_idx)
        train_doublets_idx = np.arange(train_doublets.shape[0])
        np.random.shuffle(train_doublets_idx)


        counter = 1
        start_time = time.time()

        for epoch in range(config.epoch):
            batch_idx = len(train_doublets) // self.batch_size


            for idx in range(0,batch_idx):
                batch_images_idx = train_triplets_idx[idx*self.batch_size:(idx+1)*self.batch_size]
                batch_images = train_triplets[batch_images_idx]

                batch_zs_idx = train_doublets_idx[idx*self.batch_size:(idx+1)*self.batch_size]
                batch_zs = train_doublets[batch_zs_idx]



                # Update D network
                _, summary_str = self.sess.run([d_optim, self.d_sum],
                                               feed_dict={
                                                   self.triplets: batch_images,
                                                   self.doublets: batch_zs,
                                                   self.is_training: True
                                               })
                self.writer.add_summary(summary_str, counter)

                # Update G Network
                _, summary_str = self.sess.run([g_optim, self.g_sum],
                                               feed_dict={
                                                   self.doublets: batch_zs,
                                                   self.is_training: True
                                               })
                self.writer.add_summary(summary_str, counter)

                counter += 1

                errD_fake = self.d_loss_fake.eval({ self.doublets: batch_zs, self.is_training: True})
                errD_real = self.d_loss_real.eval({ self.triplets: batch_images, self.is_training: True})
                errG = self.g_loss.eval({self.doublets: batch_zs, self.is_training: True})

                print("Epoch: [%2d] [%4d/%4d] time: %4.4f, d_loss %.8f, g_loss %.8f0" \
                      % (epoch, idx, batch_idx, time.time() - start_time, errD_fake+errD_real, errG))

            summary_str = self.sess.run(self.img_sum,
                                           feed_dict = {
                                               self.doublets: train_doublets[0:self.batch_size],
                                               self.is_training: True
                                           })
            self.writer.add_summary(summary_str, counter)

            if np.mod(epoch, 5) == 0:
                self.save(config.checkpoint_dir, counter)

    @property
    def model_dir(self):
        return "{}_{}_{}_{}".format(
            self.dataset_name, self.batch_size,
            self.input_height, self.input_width)

    def save(self, checkpoint_dir, step):
        model_name = "DCGAN.model"
        checkpoint_dir = os.path.join(checkpoint_dir, self.model_dir)

        if not os.path.exists(checkpoint_dir):
            os.makedirs(checkpoint_dir)

        self.saver.save(self.sess,
                        os.path.join(checkpoint_dir, model_name),
                        global_step=step)

    def load(self, checkpoint_dir):
        import re
        print(" [*] Reading checkpoints...")
        checkpoint_dir = os.path.join(checkpoint_dir, self.model_dir)

        ckpt = tf.train.get_checkpoint_state(checkpoint_dir)
        if ckpt and ckpt.model_checkpoint_path:
            ckpt_name = os.path.basename(ckpt.model_checkpoint_path)
            self.saver.restore(self.sess, os.path.join(checkpoint_dir, ckpt_name))
            counter = int(next(re.finditer("(\d+)(?!.*\d)", ckpt_name)).group(0))
            print(" [*] Success to read {}".format(ckpt_name))
            return True, counter
        else:
            print(" [*] Failed to find a checkpoint")
            return False, 0
