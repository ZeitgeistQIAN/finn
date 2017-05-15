from __future__ import division
import os
import time
import math
from glob import glob
import tensorflow as tf
import numpy as np

from ops import *
from datasets import *
from model import *

class Config:

    def __init__(self, epoch, learning_rate, beta1, batch_size):
        self.epoch = epoch
        self.learning_rate = learning_rate
        self.beta1 = beta1
        self.batch_size = batch_size
        self.checkpoint_dir = './chkpts'



if __name__ == '__main__':

    cfg = Config(epoch=10, learning_rate=.001, beta1=0.5, batch_size=64)

    run_config = tf.ConfigProto()
    run_config.gpu_options.allow_growth = True

    with tf.Session(config=run_config) as sess:

        df_dim = 8
        batch_size = cfg.batch_size
        writer_path = './summaries'
        video_path = './datasets/bus_cif.y4m'
        finn = Finn(sess, df_dim, batch_size, writer_path, video_path)
        finn.build_model()
        finn.train(cfg)
