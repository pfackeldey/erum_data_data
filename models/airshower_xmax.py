from functools import cached_property
from template import NetworkABC
import tensorflow as tf
import numpy as np

from erum_data_data.erum_data_data import Airshower


def resolution(y_true, y_pred):
    """ Metric to control for standart deviation """
    mean, var = tf.nn.moments((y_true - y_pred), axes=[0])
    return tf.sqrt(var)


def NormToLabel(stats, factor=1, name=None):
    return tf.keras.layers.Lambda(lambda x: factor * stats["std"] * x + stats["mean"], name=name)


def recurrent_block(input, nodes=10):
    # fmt: off
    x = tf.keras.layers.TimeDistributed(tf.keras.layers.TimeDistributed(
        tf.keras.layers.Bidirectional(tf.keras.layers.LSTM(32, return_sequences=True))))(input)
    x = tf.keras.layers.TimeDistributed(tf.keras.layers.TimeDistributed(
        tf.keras.layers.LSTM(nodes, return_sequences=False)))(x)
    # fmt: on
    return tf.keras.layers.Reshape((x.shape[1], x.shape[2], nodes))(x)


def residual_unit(input, nfilter, f_size=3, bottleneck=False, batchnorm=True):
    if bottleneck:
        # bottleneck layer
        input = tf.keras.layers.Conv2D(nfilter, 1, padding="same", activation="relu")(input)
    x = tf.keras.layers.Conv2D(nfilter, f_size, padding="same")(input)
    if batchnorm:
        x = tf.keras.layers.BatchNormalization()(x)
    x = tf.keras.layers.Activation("relu")(x)
    x = tf.keras.layers.Conv2D(nfilter, f_size, padding="same")(x)
    if batchnorm:
        x = tf.keras.layers.BatchNormalization()(x)
    out = tf.keras.layers.Add()([x, input])
    return tf.keras.layers.Activation("relu")(out)


def ResNet(input):
    x = residual_unit(input, 64, bottleneck=True)
    x = residual_unit(x, 64)
    x = residual_unit(x, 64)
    x = residual_unit(x, 64)
    x = residual_unit(x, 64)
    x = tf.keras.layers.MaxPooling2D()(x)
    x = residual_unit(x, 128, bottleneck=True)
    x = residual_unit(x, 128)
    x = residual_unit(x, 128)
    x = residual_unit(x, 128)
    x = residual_unit(x, 128)
    return x


def norm_time(time, std=None):
    u = np.isnan(time)
    time -= np.nanmean(time, axis=(1, 2, 3), keepdims=True)

    if std is None:
        std = np.nanstd(time)

    time /= std
    time[u] = 0
    return time, std


def norm_signal(signal):
    signal[np.less(signal, 0)] = 0
    signal = np.log10(signal + 1)
    signal[np.isnan(signal)] = 0
    return signal


class OptsMixin:
    @property
    def callbacks(self):
        return super().callbacks.append(
            [
                tf.keras.callbacks.ReduceLROnPlateau(
                    monitor="val_loss",
                    factor=0.5,
                    patience=4,
                    verbose=1,
                    mode="auto",
                    min_delta=0,
                    min_lr=1e-4,
                ),
                tf.keras.callbacks.EarlyStopping(
                    monitor="val_loss",
                    min_delta=0.0001,
                    patience=10,
                    restore_best_weights=True,
                ),
            ]
        )

    @property
    def metrics(self):
        return super().metrics.append(resolution)

    @property
    def compile_args(self):
        return dict(
            super().compile_args,
            loss="mse",
            optimizer=tf.keras.optimizers.Adam(lr=3e-3, amsgrad=True),
        )

    @property
    def fit_args(self):
        return dict(
            super().fit_args,
            batch_size=32,
            epochs=50,
            verbose=2,
            validation_split=0.1,
            shuffle=True,
        )


class Network(NetworkABC, OptsMixin):
    compatible_datasets = [Airshower]

    def preprocessing(self, in_data):
        time, _ = norm_time(in_data["time"], self.std)
        signal = norm_signal(in_data["signal"])
        return [signal, time]

    @cached_property
    def load_train(self):
        return Airshower.load(split="train")

    @cached_property
    def stats(self):
        _, y_train = self.load_train
        return dict(std=np.std(y_train), mean=np.mean(y_train))

    @cached_property
    def std(self):
        x_train, _ = self.load_train
        _, std = norm_time(x_train["time"])
        return std

    def get_shapes(self, in_data):
        # assume (see: preprocessing):
        #   in_data[0] := signal
        #   in_data[1] := time
        return [in_data[0].shape[1:], in_data[1].shape[1:]]

    def model(self, ds, shapes, save_model_png=False):
        assert ds in self.compatible_datasets

        # Input Cube from time traces
        sig_in = tf.keras.layers.Input(shape=shapes[0], name="signal")
        # T0 input
        time_in = tf.keras.layers.Input(shape=shapes[1], name="time")
        TimeProcess = tf.keras.layers.Reshape(sig_in.shape.as_list()[1:] + [1])(sig_in)
        # Time trace characterization
        TimeProcess = recurrent_block(TimeProcess)
        x = tf.keras.layers.Concatenate()([TimeProcess, time_in])
        x = ResNet(x)
        x = tf.keras.layers.GlobalMaxPooling2D()(x)
        x = tf.keras.layers.Dropout(0.3)(x)
        x = tf.keras.layers.Dense(1)(x)
        output = NormToLabel(self.stats)(x)
        return tf.keras.Model(inputs=[sig_in, time_in], outputs=output)