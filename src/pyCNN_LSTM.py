import tensorflow as tf
from tensorflow import keras
from tensorflow.keras import backend as K
from tensorflow.keras import layers
from tensorflow.keras.activations import relu, sigmoid
from tensorflow.keras.initializers import orthogonal, he_uniform


def __transition_block(x, reduction, name):
    """A transition block of densenet for 1D data.

    Arguments:
      x: input tensor.
      reduction: float, compression rate at transition layers.
      name: string, block label.

    Returns:
      output tensor for the block.
    """
    bn_axis = 2
    x = layers.BatchNormalization(axis=2, epsilon=1.001e-5, name=name + '_bn')(x)
    x = layers.Activation('relu', name=name + '_relu')(x)
    x = layers.Conv1D(int(x.shape[bn_axis] * reduction), 1, use_bias=False, name=name + '_conv')(x)
    x = layers.AveragePooling1D(2, strides=2, name=name + '_pool')(x)
    return x


def __conv_block(x, growth_rate, name):
    """A building block for a dense block from densenet for 1D data.

    Arguments:
      x: input tensor.
      growth_rate: float, growth rate at dense layers.
      name: string, block label.

    Returns:
      Output tensor for the block.
    """
    bn_axis = 2  # 3 if backend.image_data_format() == 'channels_last' else 1
    x1 = layers.BatchNormalization(axis=bn_axis, epsilon=1.001e-5, name=name + '_0_bn')(x)
    x1 = layers.Activation('relu', name=name + '_0_relu')(x1)
    x1 = layers.Conv1D(4 * growth_rate, 1, use_bias=False, name=name + '_1_conv')(x1)
    x1 = layers.BatchNormalization(axis=bn_axis, epsilon=1.001e-5, name=name + '_1_bn')(x1)
    x1 = layers.Activation('relu', name=name + '_1_relu')(x1)
    x1 = layers.Conv1D(growth_rate, 3, padding='same', use_bias=False, name=name + '_2_conv')(x1)
    x = layers.Concatenate(axis=bn_axis, name=name + '_concat')([x, x1])
    return x


def __dense_block(x, blocks, growth_rate, name):
    """A dense block of densenet for 1D data.

    Arguments:
      x: input tensor.
      blocks: integer, the number of building blocks.
      name: string, block label.

    Returns:
      Output tensor for the block.
    """
    for i in range(blocks):
        x = __conv_block(x, growth_rate, name=name + '_block' + str(i + 1))
    return x


def __se_module(x, dense_units):
    """
    SE Module of CaiWenjuan:

    References
    ----------
     Squeeze-and-Excitation Networks, Jie Hu, Li Shen, Samuel Albanie, Gang Sun, Enhua Wu (arXiv:1709.01507v4)

    Arguments
    ---------
      x: input tensor.
      dense_units: integer, the number units on each dense layer

    Returns
    -------
      Output tensor for the block.
    """
    se = layers.GlobalAveragePooling1D()(x)
    # Reshape the output to mach the number of dimensions of the input shape: (None, 1, Channels)
    se = layers.Reshape(target_shape=(1, x.shape[2]))(se)
    se = layers.Dense(units=dense_units, activation=relu)(se)  # Fully-Connected 1
    se = layers.Dense(units=x.shape[2], activation=sigmoid)(se)  # Fully-Connected 2

    # Perform the element-wise multiplication between the inputs and the Squeeze
    se = layers.multiply([x, se])
    return se


def __check_inputs(include_top, weights, input_tensor, input_shape, classes, classifier_activation):
    """
        Auxiliar function for checking the input parameters of the models.
    """
    if include_top:
        if not isinstance(classes, int):
            raise ValueError("'classes' must be an int value.")
        act = keras.activations.get(classifier_activation)
        if act not in {keras.activations.get('softmax'), keras.activations.get(None)}:
            raise ValueError("'classifier_activation' must be 'softmax' or None.")

    if weights is not None and not tf.io.gfile.exists(weights):
        raise ValueError("'weights' path does not exists: ", weights)

    # Determine input
    if input_tensor is None:
        if input_shape is not None:
            inp = layers.Input(shape=input_shape)
        else:
            raise ValueError("One of input_tensor or input_shape should not be None.")
    else:
        inp = input_tensor

    return inp


def OhShuLih(include_top=True,
             weights=None,
             input_tensor=None,
             input_shape=None,
             classes=5,
             classifier_activation="softmax"):
    """
    CNN+LSTM model for Arrythmia classification.

    Parameters
    ----------
        include_top: bool, default=True
          Whether to include the fully-connected layer at the top of the network.

        weights: str, default=None
            The path to the weights file to be loaded.

        input_tensor: keras.Tensor, defaults=None
            Optional Keras tensor (i.e. output of `layers.Input()`) to use as input for the model.

        input_shape: Tuple, defaults=None
            If `input_tensor=None`, a tuple that defines the input shape for the model.

        classes: int, defaults=5
            If `include_top=True`, the number of units in the top layer to classify data.

        classifier_activation: str or callable, defaults='softmax'
            The activation function to use on the "top" layer. Ignored unless `include_top=True`. Set
            `classifier_activation=None` to return the logits of the "top" layer.

    Returns
    -------
    `keras.Model`
        A `keras.Model` instance.

    References
    ----------
        `Oh, Shu Lih, et al. "Automated diagnosis of arrhythmia using combination of CNN and LSTM techniques with
        variable length heart beats." Computers in biology and medicine 102 (2018): 278-287.`
    """
    def full_convolution(x, filters, kernel_size, **kwargs):
        # Do a full convolution. Return a keras Tensor
        x = layers.ZeroPadding1D(padding=kernel_size - 1)(x)
        x = layers.Conv1D(filters=filters, kernel_size=kernel_size, **kwargs)(x)
        return x

    # Initial checks
    inp = __check_inputs(include_top, weights, input_tensor, input_shape, classes, classifier_activation)

    # Model Definition
    x = full_convolution(inp, filters=3, kernel_size=20, activation=relu, use_bias=False, strides=1)
    x = layers.MaxPooling1D(pool_size=2)(x)
    x = full_convolution(x, filters=6, kernel_size=10, activation=relu, use_bias=False, strides=1)
    x = layers.MaxPooling1D(pool_size=2)(x)
    x = full_convolution(x, filters=6, kernel_size=5, activation=relu, use_bias=False, strides=1)
    x = layers.MaxPooling1D(pool_size=2)(x)
    x = layers.LSTM(units=20, recurrent_dropout=0.2)(x)

    if include_top:
        x = layers.Dropout(rate=0.2)(x)
        x = layers.Dense(units=20, activation=relu)(x)
        x = layers.Dense(units=10, activation=relu)(x)
        x = layers.Dense(units=classes, activation=classifier_activation)(x)

    model = keras.Model(inputs=inp, outputs=x, name="OhShuLih")

    # Load weights
    if weights is not None:
        model.load_weights(weights)

    return model


def KhanZulfiqar(include_top=True,
                 weights=None,
                 input_tensor=None,
                 input_shape=None,
                 gru_units=(100, 50),
                 return_sequences=False,
                 classes=5,
                 classifier_activation="softmax"):
    """
    CNN+GRU model for electricity forecasting

    Parameters
    ----------
        include_top: bool, default=True
          Whether to include the fully-connected layer at the top of the network.

        weights: str, default=None
            The path to the weights file to be loaded.

        input_tensor: keras.Tensor, defaults=None
            Optional Keras tensor (i.e. output of `layers.Input()`) to use as input for the model.

        input_shape: Tuple, defaults=None
            If `input_tensor=None`, a tuple that defines the input shape for the model.

        gru_units: Tuple of length=2, defaults=(100, 50)
            The number of units within the 2 GRU layers.

        return_sequences: bool, defaults=False
            If True, the last GRU layer and Top layer if `include_top=True` returns the whole sequence instead of
            the last value.

        classes: int, defaults=5
            If `include_top=True`, the number of units in the top layer to classify data.

        classifier_activation: str or callable, defaults='softmax'
            The activation function to use on the "top" layer. Ignored unless `include_top=True`. Set
            `classifier_activation=None` to return the logits of the "top" layer.

    Returns
    -------
        model: keras.Model
            A `keras.Model` instance with the Full CNN-LSTM Autoencoder

    References
    ---------
        Sajjad, M., Khan, Z. A., Ullah, A., Hussain, T., Ullah, W., Lee, M. Y., & Baik, S. W. (2020). A novel
        CNN-GRU-based hybrid approach for short-term residential load forecasting. IEEE Access, 8, 143759-143768.
     """

    # Check inputs
    inp = __check_inputs(include_top, weights, input_tensor, input_shape, classes, classifier_activation)
    if len(gru_units) != 2:
        raise ValueError("'gru_units' must be a tuple of length 2")

    # Model Definition
    x = layers.Conv1D(filters=16, kernel_size=2, activation=relu)(inp)
    x = layers.Dropout(0.1)(x)
    x = layers.Conv1D(filters=8, kernel_size=2, activation=relu)(x)
    x = layers.Dropout(0.1)(x)
    x = layers.GRU(units=gru_units[0], return_sequences=True)(x)
    x = layers.GRU(units=gru_units[1], return_sequences=return_sequences)(x)

    if include_top:
        x = layers.Dense(units=classes, activation=classifier_activation)(x)

    model = keras.Model(inputs=inp, outputs=x, name="KhanZulfiqar")

    if weights is not None:
        model.load_weights(weights)

    return model


def ZhengZhenyu(include_top=True,
                weights=None,
                input_tensor=None,
                input_shape=None,
                classes=5,
                classifier_activation="softmax"):
    """

    CNN+LSTM network for arrythmia detection. This model initialy was designed to deal with 2D images. It was adapted
    to 1D time series.

    Parameters
    ----------
        include_top: bool, default=True
            Whether to include the fully-connected layer at the top of the network.

        weights: str, default=None
            The path to the weights file to be loaded.

        input_tensor: keras.Tensor, defaults=None
            Optional Keras tensor (i.e. output of `layers.Input()`) to use as input for the model.

        input_shape: Tuple, defaults=None
            If `input_tensor=None`, a tuple that defines the input shape for the model.

        classes: int, defaults=5
            If `include_top=True`, the number of units in the top layer to classify data.

        classifier_activation: str or callable, defaults='softmax'
            The activation function to use on the "top" layer. Ignored unless `include_top=True`. Set
            `classifier_activation=None` to return the logits of the "top" layer.

    Returns
    -------
        model: keras.Model
            A `keras.Model` instance.

    References
    ----------
        Zheng, Z., Chen, Z., Hu, F., Zhu, J., Tang, Q., & Liang, Y. (2020). An automatic diagnosis of arrhythmias using
        a combination of CNN and LSTM technology. Electronics, 9(1), 121.
    """
    inp = __check_inputs(include_top, weights, input_tensor, input_shape, classes, classifier_activation)

    # Model Definition
    x = inp
    for f in [64, 128, 256]:
        x = layers.Conv1D(filters=f, kernel_size=3, strides=1, padding='same', activation=keras.activations.elu)(x)
        x = layers.BatchNormalization()(x)
        x = layers.Conv1D(filters=f, kernel_size=3, strides=1, padding='same', activation=keras.activations.elu)(x)
        x = layers.BatchNormalization()(x)
        x = layers.MaxPooling1D(pool_size=2, strides=2)(x)

    x = layers.LSTM(units=256)(x)

    if include_top:
        x = layers.Dense(units=2048, activation=keras.activations.elu)(x)
        x = layers.Dropout(rate=0.5)(x)
        x = layers.Dense(units=2048, activation=keras.activations.elu)(x)
        x = layers.Dense(units=classes, activation=classifier_activation)(x)

    model = keras.Model(inputs=inp, outputs=x, name="ZhengZhenyu")

    # Load weights
    if weights is not None:
        model.load_weights(weights)

    return model


def HouBoroui(include_top=True,
              weights=None,
              input_tensor=None,
              input_shape=None,
              classes=5,
              classifier_activation="softmax"):
    """
    References
    ----------
        Hou, Borui, et al. "LSTM based auto-encoder model for ECG arrhythmias classification." IEEE Transactions on
        Instrumentation and Measurement (2019).

    Parameters
    ----------
         include_top: bool, default=True

           Whether to include the fully-connected layer at the top of the network.

        weights: str, default=None

            The path to the weights file to be loaded.

        input_tensor: keras.Tensor, defaults=None

            Optional Keras tensor (i.e. output of `layers.Input()`) to use as input for the model.

        input_shape: Tuple, defaults=None

            If `input_tensor=None`, a tuple that defines the input shape for the model.

        classes: int, defaults=5

            If `include_top=True`, the number of units in the top layer to classify data.

        classifier_activation: str or callable, defaults='softmax'

            The activation function to use on the "top" layer. Ignored unless `include_top=True`. Set
            `classifier_activation=None` to return the logits of the "top" layer.

    Returns
    -------

        A `keras.Model` instance.
    """
    inp = __check_inputs(include_top, weights, input_tensor, input_shape, classes, classifier_activation)

    # Model definition
    x = layers.LSTM(units=146, return_sequences=True)(inp)
    x = layers.LSTM(units=31, return_sequences=True)(x)

    if include_top:
        x = layers.Flatten()(x)
        x = layers.Dense(units=classes, activation=classifier_activation)(x)

    model = keras.Model(inputs=inp, outputs=x, name="HouBoroui")

    if weights is not None:
        model.load_weights(weights)

    return model


def WangKejun(include_top=True,
              weights=None,
              input_tensor=None,
              input_shape=None,
              classes=5,
              classifier_activation="softmax"):
    """
    References
    ----------
        Wang, Kejun, Xiaoxia Qi, and Hongda Liu. "Photovoltaic power forecasting based LSTM-Convolutional Network."
        Energy 189 (2019): 116225.

    Parameters
    ----------
         include_top: bool, default=True

           Whether to include the fully-connected layer at the top of the network.

        weights: str, default=None

            The path to the weights file to be loaded.

        input_tensor: keras.Tensor, defaults=None

            Optional Keras tensor (i.e. output of `layers.Input()`) to use as input for the model.

        input_shape: Tuple, defaults=None

            If `input_tensor=None`, a tuple that defines the input shape for the model.

        classes: int, defaults=5

            If `include_top=True`, the number of units in the top layer to classify data.

        classifier_activation: str or callable, defaults='softmax'

            The activation function to use on the "top" layer. Ignored unless `include_top=True`. Set
            `classifier_activation=None` to return the logits of the "top" layer.

    Returns
    -------

        A `keras.Model` instance.
    """
    inp = __check_inputs(include_top, weights, input_tensor, input_shape, classes, classifier_activation)

    # Model definition
    x = layers.LSTM(64, return_sequences=True)(inp)
    x = layers.LSTM(128, return_sequences=True)(x)
    x = layers.Conv1D(filters=64, kernel_size=3, strides=1)(x)
    x = layers.MaxPooling1D(2, strides=2)(x)
    x = layers.Conv1D(filters=150, kernel_size=2, strides=1)(x)
    x = layers.MaxPooling1D(2, strides=2)(x)
    x = layers.Dropout(0.1)(x)

    if include_top:
        x = layers.Flatten()(x)
        x = layers.Dense(units=classes, activation=classifier_activation)(x)

    model = keras.Model(inputs=inp, outputs=x, name="WangKejun")

    if weights is not None:
        model.load_weights(weights)

    return model


def ChenChen(include_top=True,
             weights=None,
             input_tensor=None,
             input_shape=None,
             classes=5,
             classifier_activation="softmax"):
    """
    References
    ----------
        Chen, Chen, et al. "Automated arrhythmia classification based on a combination network of CNN and LSTM."
        Biomedical Signal Processing and Control 57 (2020): 101819.

    Parameters
    ----------
         include_top: bool, default=True

           Whether to include the fully-connected layer at the top of the network.

        weights: str, default=None

            The path to the weights file to be loaded.

        input_tensor: keras.Tensor, defaults=None

            Optional Keras tensor (i.e. output of `layers.Input()`) to use as input for the model.

        input_shape: Tuple, defaults=None

            If `input_tensor=None`, a tuple that defines the input shape for the model.

        classes: int, defaults=5

            If `include_top=True`, the number of units in the top layer to classify data.

        classifier_activation: str or callable, defaults='softmax'

            The activation function to use on the "top" layer. Ignored unless `include_top=True`. Set
            `classifier_activation=None` to return the logits of the "top" layer.

    Returns
    -------

        A `keras.Model` instance.
    """
    inp = __check_inputs(include_top, weights, input_tensor, input_shape, classes, classifier_activation)

    # Model definition
    x = inp
    for f in [251, 150, 100, 81, 61, 14]:
        x = layers.Conv1D(filters=f, kernel_size=2, strides=1)(x)
        x = layers.MaxPooling1D(pool_size=2, strides=1)(x)
    x = layers.LSTM(units=64, return_sequences=True)(x)
    x = layers.LSTM(units=32, return_sequences=True)(x)

    if include_top:
        x = layers.Flatten()(x)
        x = layers.Dense(units=classes, activation=classifier_activation)(x)

    model = keras.Model(inputs=inp, outputs=x, name="ChenChen")

    if weights is not None:
        model.load_weights(weights)

    return model


def KimTaeYoung(include_top=True,
                weights=None,
                input_tensor=None,
                input_shape=None,
                classes=5,
                classifier_activation="softmax"):
    """
    References
    ----------
        Kim, Tae-Young, and Sung-Bae Cho. "Predicting residential energy consumption using CNN-LSTM neural networks."
        Energy 182 (2019): 72-81.

    Parameters
    ----------
         include_top: bool, default=True

           Whether to include the fully-connected layer at the top of the network.

        weights: str, default=None

            The path to the weights file to be loaded.

        input_tensor: keras.Tensor, defaults=None

            Optional Keras tensor (i.e. output of `layers.Input()`) to use as input for the model.

        input_shape: Tuple, defaults=None

            If `input_tensor=None`, a tuple that defines the input shape for the model.

        classes: int, defaults=5

            If `include_top=True`, the number of units in the top layer to classify data.

        classifier_activation: str or callable, defaults='softmax'

            The activation function to use on the "top" layer. Ignored unless `include_top=True`. Set
            `classifier_activation=None` to return the logits of the "top" layer.

    Returns
    -------

        A `keras.Model` instance.
    """
    inp = __check_inputs(include_top, weights, input_tensor, input_shape, classes, classifier_activation)

    # Model definition
    x = inp
    for f in [64, 150]:
        x = layers.Conv1D(filters=f, kernel_size=2, strides=1)(x)
        x = layers.MaxPooling1D(pool_size=2, strides=1)(x)
    x = layers.LSTM(units=64, activation=keras.activations.tanh, return_sequences=True)(x)

    if include_top:
        x = layers.Flatten()(x)
        x = layers.Dense(units=classes, activation=classifier_activation)(x)

    model = keras.Model(inputs=inp, outputs=x, name="KimTaeYoung")

    if weights is not None:
        model.load_weights(weights)

    return model


def GenMinxing(include_top=True,
               weights=None,
               input_tensor=None,
               input_shape=None,
               classes=5,
               classifier_activation="softmax"):
    """
    References
    ----------
        Geng, Minxing, et al. "Epileptic Seizure Detection Based on Stockwell Transform and Bidirectional Long
        Short-Term Memory." IEEE Transactions on Neural Systems and Rehabilitation Engineering 28.3 (2020): 573-580.

    Parameters
    ----------
         include_top: bool, default=True

           Whether to include the fully-connected layer at the top of the network.

        weights: str, default=None

            The path to the weights file to be loaded.

        input_tensor: keras.Tensor, defaults=None

            Optional Keras tensor (i.e. output of `layers.Input()`) to use as input for the model.

        input_shape: Tuple, defaults=None

            If `input_tensor=None`, a tuple that defines the input shape for the model.

        classes: int, defaults=5

            If `include_top=True`, the number of units in the top layer to classify data.

        classifier_activation: str or callable, defaults='softmax'

            The activation function to use on the "top" layer. Ignored unless `include_top=True`. Set
            `classifier_activation=None` to return the logits of the "top" layer.

    Returns
    -------

        A `keras.Model` instance.
    """
    inp = __check_inputs(include_top, weights, input_tensor, input_shape, classes, classifier_activation)

    # Model definition
    x = layers.Bidirectional(layers.LSTM(units=40, return_sequences=True))(inp)
    if include_top:
        x = layers.Flatten()(x)
        x = layers.Dense(units=classes, activation=classifier_activation)(x)

    model = keras.Model(inputs=inp, outputs=x, name="GenMixing")

    if weights is not None:
        model.load_weights(weights)

    return model


def FuJiangmeng(include_top=True,
                weights=None,
                input_tensor=None,
                input_shape=None,
                classes=5,
                classifier_activation="softmax"):
    """
    References
    ----------
        Fu, Jiangmeng, et al. "A hybrid CNN-LSTM model based actuator fault diagnosis for six-rotor UAVs." 2019
        Chinese Control And Decision Conference (CCDC). IEEE, 2019.

    Parameters
    ----------
         include_top: bool, default=True

           Whether to include the fully-connected layer at the top of the network.

        weights: str, default=None

            The path to the weights file to be loaded.

        input_tensor: keras.Tensor, defaults=None

            Optional Keras tensor (i.e. output of `layers.Input()`) to use as input for the model.

        input_shape: Tuple, defaults=None

            If `input_tensor=None`, a tuple that defines the input shape for the model.

        classes: int, defaults=5

            If `include_top=True`, the number of units in the top layer to classify data.

        classifier_activation: str or callable, defaults='softmax'

            The activation function to use on the "top" layer. Ignored unless `include_top=True`. Set
            `classifier_activation=None` to return the logits of the "top" layer.

    Returns
    -------

        A `keras.Model` instance.
    """
    inp = __check_inputs(include_top, weights, input_tensor, input_shape, classes, classifier_activation)

    # Model definition
    x = layers.Conv1D(filters=32, kernel_size=1, padding='same', activation=relu)(inp)
    x = layers.MaxPooling1D(pool_size=2, strides=1)(x)
    x = layers.LSTM(units=256, activation=relu, return_sequences=True)(x)

    if include_top:
        x = layers.Flatten()(x)
        x = layers.Dense(units=classes, activation=classifier_activation)(x)

    model = keras.Model(inputs=inp, outputs=x, name="FuJiangmeng")

    if weights is not None:
        model.load_weights(weights)

    return model


def ShiHaotian(include_top=True,
               weights=None,
               input_tensor=None,
               input_shape=None,
               classes=5,
               classifier_activation="softmax"):
    """
    References
    ----------
        Shi, Haotian, et al. "Automated heartbeat classification based on deep neural network with multiple input
        layers." Knowledge-Based Systems 188 (2020): 105036.

    Parameters
    ----------
         include_top: bool, default=True

           Whether to include the fully-connected layer at the top of the network.

        weights: str, default=None

            The path to the weights file to be loaded.

        input_tensor: keras.Tensor, defaults=None

            Optional Keras tensor (i.e. output of `layers.Input()`) to use as input for the model.

        input_shape: Tuple, defaults=None

            If `input_tensor=None`, a tuple that defines the input shape for the model.

        classes: int, defaults=5

            If `include_top=True`, the number of units in the top layer to classify data.

        classifier_activation: str or callable, defaults='softmax'

            The activation function to use on the "top" layer. Ignored unless `include_top=True`. Set
            `classifier_activation=None` to return the logits of the "top" layer.

    Returns
    -------

        A `keras.Model` instance.
    """
    inp = __check_inputs(include_top, weights, input_tensor, input_shape, classes, classifier_activation)

    # Model Definition
    x1 = layers.Conv1D(filters=32, kernel_size=13, strides=2, activation=relu)(inp)
    x1 = layers.MaxPooling1D(pool_size=2, strides=2)(x1)

    x2 = layers.Conv1D(filters=32, kernel_size=13, strides=1, activation=relu)(inp)
    x2 = layers.MaxPooling1D(pool_size=2, strides=2)(x2)

    x3 = layers.Conv1D(filters=32, kernel_size=13, strides=2, activation=relu)(inp)
    x3 = layers.MaxPooling1D(pool_size=2, strides=2)(x3)

    x = layers.Concatenate(axis=1)([x1, x2, x3])
    x = layers.LSTM(units=32, return_sequences=True)(x)

    if include_top:
        x = layers.Flatten()(x)
        x = layers.Dense(units=classes, activation=classifier_activation)(x)

    model = keras.Model(inputs=inp, outputs=x, name="ShiHaotian")

    if weights is not None:
        model.load_weights(weights)

    return model


def HuangMeiLing(include_top=True,
                weights=None,
                input_tensor=None,
                input_shape=None,
                classes=5,
                classifier_activation="softmax"):
    """
     CNN model, employed for 2-D images of ECG data. This model is adapted for 1-D time series

     References
     -------
         Huang, Mei-Ling, and Yan-Sheng Wu. "Classification of atrial fibrillation and normal sinus rhythm based on
         convolutional neural network." Biomedical Engineering Letters (2020): 1-11.


    Parameters
    ----------
         include_top: bool, default=True

           Whether to include the fully-connected layer at the top of the network.

        weights: str, default=None

            The path to the weights file to be loaded.

        input_tensor: keras.Tensor, defaults=None

            Optional Keras tensor (i.e. output of `layers.Input()`) to use as input for the model.

        input_shape: Tuple, defaults=None

            If `input_tensor=None`, a tuple that defines the input shape for the model.

        classes: int, defaults=5

            If `include_top=True`, the number of units in the top layer to classify data.

        classifier_activation: str or callable, defaults='softmax'

            The activation function to use on the "top" layer. Ignored unless `include_top=True`. Set
            `classifier_activation=None` to return the logits of the "top" layer.

    Returns
    -------

        A `keras.Model` instance.
     """
    inp = __check_inputs(include_top, weights, input_tensor, input_shape, classes, classifier_activation)

    # Model definition
    x = inp
    for f, k, s in zip([48, 256],
                       [15, 13],
                       [6, 1]):
        x = layers.Conv1D(filters=f, kernel_size=k, strides=s, activation=relu)(x)
        x = layers.MaxPooling1D(pool_size=2, strides=1)(x)

    if include_top:
        x = layers.Flatten()(x)
        x = layers.Dense(units=classes, activation=classifier_activation)(x)

    model = keras.Model(inputs=inp, outputs=x, name="HuangMeiLing")

    if weights is not None:
        model.load_weights(weights)

    return model


def LihOhShu(include_top=True,
             weights=None,
             input_tensor=None,
             input_shape=None,
             classes=5,
             classifier_activation="softmax"):
    """
    CNN+LSTM model

    References
    ----------
        Lih, Oh Shu, et al. "Comprehensive electrocardiographic diagnosis based on deep learning." Artificial
        Intelligence in Medicine 103 (2020): 101789.

    Parameters
    ----------
         include_top: bool, default=True

           Whether to include the fully-connected layer at the top of the network.

        weights: str, default=None

            The path to the weights file to be loaded.

        input_tensor: keras.Tensor, defaults=None

            Optional Keras tensor (i.e. output of `layers.Input()`) to use as input for the model.

        input_shape: Tuple, defaults=None

            If `input_tensor=None`, a tuple that defines the input shape for the model.

        classes: int, defaults=5

            If `include_top=True`, the number of units in the top layer to classify data.

        classifier_activation: str or callable, defaults='softmax'

            The activation function to use on the "top" layer. Ignored unless `include_top=True`. Set
            `classifier_activation=None` to return the logits of the "top" layer.

    Returns
    -------

        A `keras.Model` instance.

    """
    inp = __check_inputs(include_top, weights, input_tensor, input_shape, classes, classifier_activation)

    # Model definition
    x = inp
    for filters, k_size in zip([3, 6, 6, 6, 6],
                               [20, 10, 5, 5, 10]):
        x = layers.Conv1D(filters=filters, activation=relu, kernel_size=k_size, strides=1)(x)
        x = layers.MaxPooling1D(pool_size=2, strides=1)(x)

    x = layers.LSTM(units=10, return_sequences=True)(x)

    if include_top:
        x = layers.Flatten()(x)
        x = layers.Dense(units=classes, activation=classifier_activation)(x)

    model = keras.Model(inputs=inp, outputs=x, name="LihOhShu")

    if weights is not None:
        model.load_weights(weights)

    return model


def GaoJunLi(include_top=True,
             weights=None,
             input_tensor=None,
             input_shape=None,
             classes=5,
             classifier_activation="softmax"):
    """
    LSTM network

    References
    ----------
        Gao, Junli, et al. "An Effective LSTM Recurrent Network to Detect Arrhythmia on Imbalanced ECG Dataset."
        Journal of healthcare engineering 2019 (2019).

    Parameters
    ----------
         include_top: bool, default=True

           Whether to include the fully-connected layer at the top of the network.

        weights: str, default=None

            The path to the weights file to be loaded.

        input_tensor: keras.Tensor, defaults=None

            Optional Keras tensor (i.e. output of `layers.Input()`) to use as input for the model.

        input_shape: Tuple, defaults=None

            If `input_tensor=None`, a tuple that defines the input shape for the model.

        classes: int, defaults=5

            If `include_top=True`, the number of units in the top layer to classify data.

        classifier_activation: str or callable, defaults='softmax'

            The activation function to use on the "top" layer. Ignored unless `include_top=True`. Set
            `classifier_activation=None` to return the logits of the "top" layer.

    Returns
    -------

        A `keras.Model` instance.
    """
    inp = __check_inputs(include_top, weights, input_tensor, input_shape, classes, classifier_activation)

    # Model definition
    x = layers.LSTM(units=64, return_sequences=True)(inp)

    if include_top:
        x = layers.Flatten()(x)
        x = layers.Dense(units=classes, activation=classifier_activation)(x)

    model = keras.Model(inputs=inp, outputs=x, name="GaoJunLi")

    if weights is not None:
        model.load_weights(weights)

    return model


def WeiXiaoyan(include_top=True,
               weights=None,
               input_tensor=None,
               input_shape=None,
               classes=5,
               classifier_activation="softmax"):
    """
     CNN+LSTM model employed for 2-D images of ECG data. This model is adapted for 1-D time series.


     References
     ----------

         Wei, Xiaoyan, et al. "Early prediction of epileptic seizures using a long-term recurrent convolutional
         network." Journal of neuroscience methods 327 (2019): 108395.

    Parameters
    ----------
         include_top: bool, default=True

           Whether to include the fully-connected layer at the top of the network.

        weights: str, default=None

            The path to the weights file to be loaded.

        input_tensor: keras.Tensor, defaults=None

            Optional Keras tensor (i.e. output of `layers.Input()`) to use as input for the model.

        input_shape: Tuple, defaults=None

            If `input_tensor=None`, a tuple that defines the input shape for the model.

        classes: int, defaults=5

            If `include_top=True`, the number of units in the top layer to classify data.

        classifier_activation: str or callable, defaults='softmax'

            The activation function to use on the "top" layer. Ignored unless `include_top=True`. Set
            `classifier_activation=None` to return the logits of the "top" layer.

    Returns
    -------

        A `keras.Model` instance.

     """
    inp = __check_inputs(include_top, weights, input_tensor, input_shape, classes, classifier_activation)

    # Model definition
    x = inp
    # Network Defintion (CNN)
    for filters, kernel, strides in zip([32, 64, 128, 256, 512],
                                        [5, 3, 3, 3, 3],
                                        [1, 1, 1, 1, 1]):
        x = layers.Conv1D(filters=filters, kernel_size=kernel, strides=strides)(x)
        x = layers.LeakyReLU(alpha=0.01)(x)
        x = layers.MaxPooling1D(pool_size=2, strides=2)(x)
        x = layers.BatchNormalization()(x)

    # LSTM
    x = layers.LSTM(units=512, return_sequences=True)(x)
    x = layers.LSTM(units=512, return_sequences=True)(x)

    if include_top:
        x = layers.Flatten()(x)
        x = layers.Dense(units=classes, activation=classifier_activation)(x)

    model = keras.Model(inputs=inp, outputs=x, name="WeiXiaoyan")

    if weights is not None:
        model.load_weights(weights)

    return model


def KongZhengmin(include_top=True,
                 weights=None,
                 input_tensor=None,
                 input_shape=None,
                 classes=5,
                 classifier_activation="softmax"):
    """
    CNN+LSTM

    References
    ----------
        Kong, Zhengmin, et al. "Convolution and Long Short-Term Memory Hybrid Deep Neural Networks for Remaining
        Useful Life Prognostics." Applied Sciences 9.19 (2019): 4156.

    Parameters
    ----------
         include_top: bool, default=True

           Whether to include the fully-connected layer at the top of the network.

        weights: str, default=None

            The path to the weights file to be loaded.

        input_tensor: keras.Tensor, defaults=None

            Optional Keras tensor (i.e. output of `layers.Input()`) to use as input for the model.

        input_shape: Tuple, defaults=None

            If `input_tensor=None`, a tuple that defines the input shape for the model.

        classes: int, defaults=5

            If `include_top=True`, the number of units in the top layer to classify data.

        classifier_activation: str or callable, defaults='softmax'

            The activation function to use on the "top" layer. Ignored unless `include_top=True`. Set
            `classifier_activation=None` to return the logits of the "top" layer.

    Returns
    -------

        A `keras.Model` instance.

    """
    inp = __check_inputs(include_top, weights, input_tensor, input_shape, classes, classifier_activation)

    # Model definition
    x = layers.Conv1D(filters=32, activation=relu, kernel_size=5, strides=1)(inp)
    x = layers.MaxPooling1D(pool_size=2, strides=2)(x)
    x = layers.LSTM(64, return_sequences=True)(x)
    x = layers.LSTM(64, return_sequences=True)(x)

    if include_top:
        x = layers.Flatten()(x)
        x = layers.Dense(units=classes, activation=classifier_activation)(x)

    model = keras.Model(inputs=inp, outputs=x, name="KongZhengmin")

    if weights is not None:
        model.load_weights(weights)

    return model


def YildirimOzal(include_top=True,
                 autoencoder_weights=None,
                 lstm_weights=None,
                 input_tensor=None,
                 input_shape=None,
                 classes=5,
                 classifier_activation="softmax"):
    """CAE-LSTM

     References
     ----------
         Yildirim, Ozal, et al. "A new approach for arrhythmia classification using deep coded features and LSTM
         networks." Computer methods and programs in biomedicine 176 (2019): 121-133.

     Parameters
    ----------
         include_top: bool, default=True

           Whether to include the fully-connected layer at the top of the network.

        autoencoder_weights: str, default=None

            The path to the weights file to be loaded for the autoencoder network

        lstm_weights: str, defaults=None

            The path to the weights file to be loaded for the lstm classifier network.

        input_tensor: keras.Tensor, defaults=None

            Optional Keras tensor (i.e. output of `layers.Input()`) to use as input for the model.

        input_shape: Tuple, defaults=None

            If `input_tensor=None`, a tuple that defines the input shape for the model.

        classes: int, defaults=5

            If `include_top=True`, the number of units in the top layer to classify data.

        classifier_activation: str or callable, defaults='softmax'

            The activation function to use on the "top" layer. Ignored unless `include_top=True`. Set
            `classifier_activation=None` to return the logits of the "top" layer.

    Returns
    -------

        autoenconder -> A `keras.Model` instance with the autoencoder.
        encoder      -> A `keras.Model` instance with only the encoder part
        model        -> A `keras.Model` instance representing the classification model which uses the encoder part.
     """
    inp = __check_inputs(include_top, None, input_tensor, input_shape, classes, classifier_activation)
    if autoencoder_weights is not None and not tf.io.gfile.exists(autoencoder_weights):
        raise ValueError("'autoencoder_weights' path does not exists: ", autoencoder_weights)
    if lstm_weights is not None and not tf.io.gfile.exists(lstm_weights):
        raise ValueError("'lstm_weights' path does not exists: ", lstm_weights)

    # Model definition
    e = layers.Conv1D(filters=16, kernel_size=5, padding='same', strides=1)(inp)
    e = layers.MaxPooling1D(pool_size=2)(e)
    e = layers.Conv1D(filters=64, kernel_size=5, padding='same', strides=1)(e)
    e = layers.BatchNormalization()(e)
    e = layers.MaxPooling1D(pool_size=2)(e)
    e = layers.Conv1D(filters=32, kernel_size=3, padding='same', strides=1)(e)
    e = layers.Conv1D(filters=1, kernel_size=3, padding='same', strides=1)(e)

    bottleneck = layers.MaxPooling1D(pool_size=2)(e)
    decoder = layers.Conv1D(filters=1, kernel_size=3, padding='same', strides=1)(bottleneck)
    decoder = layers.Conv1D(filters=32, kernel_size=3, padding='same', strides=1)(decoder)
    decoder = layers.UpSampling1D(size=2)(decoder)
    decoder = layers.Conv1D(filters=64, kernel_size=5, padding='same', strides=1)(decoder)
    decoder = layers.UpSampling1D(size=2)(decoder)
    decoder = layers.Conv1D(filters=16, kernel_size=5, padding='same', strides=1)(decoder)
    # Final Dense layer of the autoencoder
    decoder = layers.Flatten()(decoder)
    decoder = layers.Dense(units=inp.shape[1], activation=sigmoid)(decoder)

    autoencoder = keras.Model(inputs=inp, outputs=decoder, name="YildirimOzal_autoencoder")

    if autoencoder_weights is not None:
        autoencoder.load_weights(autoencoder_weights)
    encoder = keras.Model(inputs=inp, outputs=bottleneck, name="YildirimOzal_encoder")

    lstm = layers.LSTM(units=32, return_sequences=True)(bottleneck)
    if include_top:
        lstm = layers.Flatten()(lstm)
        lstm = layers.Dense(units=classes, activation=classifier_activation)(lstm)

    model = keras.Model(inputs=inp, outputs=lstm, name="YildirimOzal_classifier")

    return autoencoder, encoder, model


def CaiWenjuan(include_top=True,
               weights=None,
               input_tensor=None,
               input_shape=None,
               classes=5,
               classifier_activation="softmax"):
    """
    DDNN network presented in:

    Parameters
    ----------
        include_top: bool, default=True
            Whether to include the fully-connected layer at the top of the network.

        weights: str, default=None
            The path to the weights file to be loaded.

        input_tensor: keras.Tensor, defaults=None
            Optional Keras tensor (i.e. output of `layers.Input()`) to use as input for the model.

        input_shape: Tuple, defaults=None
            If `input_tensor=None`, a tuple that defines the input shape for the model.

        classes: int, defaults=5
            If `include_top=True`, the number of units in the top layer to classify data.

        classifier_activation: str or callable, defaults='softmax'
            The activation function to use on the "top" layer. Ignored unless `include_top=True`. Set
            `classifier_activation=None` to return the logits of the "top" layer.

    Returns
    -------
    `keras.Model`
        A `keras.Model` instance.

    References
    ----------
        `Cai, Wenjuan, et al. "Accurate detection of atrial fibrillation from 12-lead ECG using deep neural network."
        Computers in biology and medicine 116 (2020): 103378.`
   """
    inp = __check_inputs(include_top, weights, input_tensor, input_shape, classes, classifier_activation)

    # Model definition
    dense_layers = [2, 4, 6, 4]
    x1 = layers.Conv1D(filters=8, kernel_size=1, strides=1, padding='same')(inp)
    x2 = layers.Conv1D(filters=16, kernel_size=3, strides=1, padding='same')(inp)
    x3 = layers.Conv1D(filters=24, kernel_size=5, strides=1, padding='same')(inp)
    x = layers.Concatenate(axis=2)([x1, x2, x3])

    for i, n_blocks in enumerate(dense_layers):
        x = __se_module(x, dense_units=128)
        x = __dense_block(x, n_blocks, growth_rate=6, name="conv" + str(i + 1))
        x = __se_module(x, dense_units=128)
        # Last dense block does not have transition block.
        if i < len(dense_layers) - 1:
            x = __transition_block(x, reduction=0.5, name="transition" + str(i + 1))

    x = layers.GlobalAveragePooling1D()(x)

    if include_top:
        x = layers.Flatten()(x)
        x = layers.Dense(units=classes, activation=classifier_activation)(x)

    model = keras.Model(inputs=inp, outputs=x, name="CaiWenjuan")

    if weights is not None:
        model.load_weights(weights)

    return model


def KimMinGu(include_top=True,
             weights=None,  # Here, weights is a vector of paths for each model
             input_tensor=None,
             input_shape=None,
             classes=5,
             classifier_activation="softmax"):
    """
    CNN ensemble model presented in:

    References
    ----------
        Kim, M. G., Choi, C., & Pan, S. B. (2020). Ensemble Networks for User Recognition in Various Situations Based on
        Electrocardiogram. IEEE Access, 8, 36527-36535.

    Parameters
    ----------
         include_top: bool, default=True

           Whether to include the fully-connected layer at the top of the network.

        weights: array(str), default=None

            An array with the paths of the weights file for each model of the ensemble.

        input_tensor: keras.Tensor, defaults=None

            Optional Keras tensor (i.e. output of `layers.Input()`) to use as input for the model.

        input_shape: Tuple, defaults=None

            If `input_tensor=None`, a tuple that defines the input shape for the model.

        classes: int, defaults=5

            If `include_top=True`, the number of units in the top layer to classify data.

        classifier_activation: str or callable, defaults='softmax'

            The activation function to use on the "top" layer. Ignored unless `include_top=True`. Set
            `classifier_activation=None` to return the logits of the "top" layer.

    Returns
    -------
        An array with six `keras.Model` instances. One for each model of the ensemble.
   """

    # NOTE: kernel sizes are not specified in the original paper.
    # Initial checks
    inp = __check_inputs(include_top, None, input_tensor, input_shape, classes, classifier_activation)
    if weights is not None:
        for w in weights:
            if not tf.io.gfile.exists(w):
                raise ValueError("'weights' path does not exists: ", weights)

    # Begin model definition
    dropout = [0.5, 0.6, 0.6, 0.7, 0.5, 0.7]

    ensemble = []
    for d in dropout:
        model = layers.Conv1D(filters=32, kernel_size=3, padding="same", activation=relu)(inp)
        model = layers.MaxPooling1D(pool_size=2)(model)
        for f in [64, 128, 256, 512]:
            model = layers.Conv1D(filters=f, kernel_size=3, padding="same", activation=relu)(model)
            model = layers.MaxPooling1D(pool_size=2)(model)

        if include_top:
            model = layers.Flatten()(model)
            model = layers.Dense(units=1028, activation=relu)(model)
            model = layers.Dropout(d)(model)
            model = layers.Dense(units=1028, activation=relu)(model)
            model = layers.Dense(units=classes, activation=classifier_activation)(model)

        ensemble.append(keras.Model(inputs=inp, outputs=model))

    return ensemble


def HaotianShi(include_top=True,
               weights=None,
               input_tensor=None,   # inputs are 4 tensors or shapes.
               input_shape=None,
               classes=5,
               classifier_activation="softmax"):
    """
    Shi, H., Qin, C., Xiao, D., Zhao, L., & Liu, C. (2020). Automated heartbeat classification based on deep neural
    network with multiple input layers. Knowledge-Based Systems, 188, 105036.
    """

    # Check input params
    if input_shape is not None and isinstance(input_shape, list) and len(input_shape) != 4:
        raise ValueError("For this model, a list of length 4 'input_shape' values are required.")
    if input_tensor is not None and isinstance(input_tensor, list) and len(input_tensor) != 4:
        raise ValueError("For this model, a list of length 4 'input_tensor' values are required.")

    # Determine input
    if input_tensor is None:
        if input_shape is not None:
            inp = layers.Input(shape=input_shape)
        else:
            raise ValueError("One of input_tensor or input_shape should not be None.")
    else:
        inp = input_tensor

    # Model definition
    x1 = layers.Conv1D(filters=32, kernel_size=13, strides=2)(inp[0])
    x1 = layers.LeakyReLU()(x1)
    x1 = layers.MaxPooling1D(pool_size=2)(x1)

    x2 = layers.Conv1D(filters=32, kernel_size=13, strides=1)(inp[1])
    x2 = layers.LeakyReLU()(x2)
    x2 = layers.MaxPooling1D(pool_size=2)(x2)

    x3 = layers.Conv1D(filters=32, kernel_size=13, strides=2)(inp[2])
    x3 = layers.LeakyReLU()(x3)
    x3 = layers.MaxPooling1D(pool_size=2)(x3)

    x = layers.Concatenate(axis=2)([x1, x2, x3])
    x = layers.LSTM(units=32)(x)
    x = layers.Flatten()(x)

    # N_h = sqrt(n_i * n_o)
    if include_top:
        x = layers.Dense(units=518, activation=relu)(x)  # TODO: nº of units is dynamic with respect inputs and outputs
        x = layers.Dense(units=88, activation=relu)(x)
        x = layers.Concatenate()([inp[3], x])
        x = layers.Dense(units=classes, activation=classifier_activation)(x)

    model = keras.Model(inputs=inp, outputs=x, name="HaotianShi")

    if weights is not None:
        model.load_weights(weights)

    return model


def HtetMyetLynn(include_top=True,
                 weights=None,
                 input_tensor=None,
                 input_shape=None,
                 classes=5,
                 classifier_activation="softmax",
                 use_rnn="gru"):  # use_gru -> one of None, "lstm" or "gru"
    """
   Lynn, H. M., Pan, S. B., & Kim, P. (2019). A deep bidirectional GRU network model for biometric electrocardiogram
   classification based on recurrent neural networks. IEEE Access, 7, 145395-145405.

   TODO Documentation
    """
    # Check inputs
    inp = __check_inputs(include_top, weights, input_tensor, input_shape, classes, classifier_activation)

    # Model definition
    x = inp
    for filt, ker, stride in zip([30, 30, 60, 60],
                                 [5, 2, 5, 2],
                                 [2, 2, 2, 2]):
        x = layers.Conv1D(filters=filt, kernel_size=ker)(x)
        x = layers.MaxPooling1D(pool_size=stride)(x)

    # Only use the CNN, or add a Bi-directional GRU or LSTM after the CNN.
    if use_rnn is None:
        if include_top:
            x = layers.Dense(units=40, activation=sigmoid)(x)
            x = layers.Dense(units=classes, activation=classifier_activation)(x)
    elif use_rnn.lower() == 'lstm':
        # Note: Units of RNN are not specified in the original paper
        x = layers.Bidirectional(layers.LSTM(units=40, dropout=0.2))(x)
    elif use_rnn.lower() == 'gru':
        x = layers.Bidirectional(layers.GRU(units=40, dropout=0.2))(x)
    else:
        raise ValueError("'use_rnn' parameter should one of: None, lstm or gru. Given: ", use_rnn)

    # Adds classification layer only in the case of use bidrectional layers.
    if use_rnn is not None:
        if include_top:
            x = layers.Dense(units=classes, activation=classifier_activation)(x)

    model = keras.Model(inputs=inp, outputs=x, name="HtetMyetLynn")

    if weights is not None:
        model.load_weights(weights)

    return model


def ZhangJin(include_top=True,
                 weights=None,
                 input_tensor=None,
                 input_shape=None,
                 classes=5,
                 classifier_activation="softmax",
             decrease_ratio=2):
    """
    Zhang, J., Liu, A., Gao, M., Chen, X., Zhang, X., & Chen, X. (2020). ECG-based multi-class arrhythmia detection
    using spatio-temporal attention-based convolutional recurrent neural network.
    Artificial Intelligence in Medicine, 106, 101856.

    Note: The step size must be at least 1000.
    TODO Documentation
    """
    def spatial_attention(x):
        # Spatial attention module:
        shared_dense1 = layers.Dense(units=x.shape[2] // decrease_ratio, activation=relu)
        shared_dense2 = layers.Dense(units=x.shape[2], activation=relu)
        x1 = layers.GlobalAveragePooling1D()(x)
        x1 = shared_dense1(x1)
        x1 = shared_dense2(x1)
        x1 = layers.Reshape(target_shape=(1, x.shape[2]))(x1)

        x2 = layers.GlobalMaxPool1D()(x)
        x2 = shared_dense1(x2)
        x2 = shared_dense2(x2)
        x2 = layers.Reshape(target_shape=(1, x.shape[2]))(x2)

        x = layers.add([x1, x2])
        x = layers.Activation(activation=sigmoid)(x)
        return x

    def temporal_attention(x):
        # Temporal attention module
        x1 = layers.GlobalMaxPool1D(data_format='channels_first')(x)
        x1 = layers.Reshape(target_shape=(x1.shape[1], 1))(x1)

        x2 = layers.GlobalAveragePooling1D(data_format='channels_first')(x)
        x2 = layers.Reshape(target_shape=(x2.shape[1], 1))(x2)

        x = layers.Concatenate()([x1, x2])
        x = layers.Conv1D(filters=1, kernel_size=7, padding="same")(x)
        x = layers.Activation(activation=sigmoid)(x)
        return x

    # Check inputs
    inp = __check_inputs(include_top, weights, input_tensor, input_shape, classes, classifier_activation)
    x = inp

    # Model definition
    for conv_layers, filters in zip([2, 2, 3, 3, 3],
                                    [64, 128, 256, 256, 256]):  # 5-block layers
        for i in range(conv_layers):
            x = layers.Conv1D(filters=filters, kernel_size=3, padding="same")(x)
            x = layers.BatchNormalization()(x)
            x = layers.Activation(activation=relu)(x)
        x = layers.MaxPooling1D(pool_size=3)(x)
        x = layers.Dropout(rate=0.2)(x)

        # Adds attention module after each convolutional block
        x_spatial = spatial_attention(x)
        x = layers.multiply([x_spatial, x])
        x_temporal = temporal_attention(x)
        x = layers.multiply([x_temporal, x])

    x = layers.Bidirectional(layers.GRU(units=12, return_sequences=True))(x)
    x = layers.Dropout(rate=0.2)(x)
    if include_top:
        x = layers.GlobalMaxPool1D()(x)
        x = layers.Dense(units=classes, activation=classifier_activation)(x)

    model = keras.Model(inputs=inp, outputs=x, name="ZhangJin")

    if weights is not None:
        model.load_weights(weights)

    return model


def YaoQihang(include_top=True,
                 weights=None,
                 input_tensor=None,
                 input_shape=None,
                 classes=5,
                 classifier_activation="softmax"):
    """
    Yao, Q., Wang, R., Fan, X., Liu, J., & Li, Y. (2020). Multi-class Arrhythmia detection from 12-lead varied-length
    ECG using Attention-based Time-Incremental Convolutional Neural Network. Information Fusion, 53, 174-182.
    """
    # Check inputs
    inp = __check_inputs(include_top, weights, input_tensor, input_shape, classes, classifier_activation)
    x = inp

    # Model definition
    # Convolutional layers (spatial):
    for conv_layers, filters in zip([2, 2, 3, 3, 3],
                                    [64, 128, 256, 256, 256]):  # 5-block layers
        for i in range(conv_layers):
            x = layers.Conv1D(filters=filters, kernel_size=3, padding="same", kernel_initializer=he_uniform)(x)
            x = layers.BatchNormalization()(x)
            x = layers.Activation(activation=relu)(x)
        x = layers.MaxPooling1D(pool_size=3)(x)

    # Temporal layers (2 LSTM layers):
    x = layers.LSTM(units=32, return_sequences=True, dropout=0.2, kernel_initializer=orthogonal)(x)
    x = layers.LSTM(units=32, return_sequences=True, dropout=0.2, kernel_initializer=orthogonal)(x)

    # Attention module:
    if include_top:
        x1 = layers.Dense(units=32, activation=keras.activations.tanh, kernel_initializer=he_uniform)(x)
        x1 = layers.Dense(units=classes, activation=classifier_activation, kernel_initializer=he_uniform)(x1)
        x = tf.reduce_mean(x1, axis=1)

    model = keras.Model(inputs=inp, outputs=x)

    return model


def YiboGao(include_top=True,
            weights=None,
            input_tensor=None,
            input_shape=None,
            classes=5,
            classifier_activation="softmax",
            return_loss=False): # If True, also return the loss function
    """
    Gao, Y., Wang, H., & Liu, Z. (2021). An end-to-end atrial fibrillation detection by a novel residual-based temporal
    attention convolutional neural network with exponential nonlinearity loss. Knowledge-Based Systems, 212, 106589.


    Code adapted from the original implementation available at:
        https://github.com/o00O00o/RTA-CNN
    """

    def en_loss(y_true, y_pred):  # Custom loss function

        epsilon = 1.e-7
        gamma = float(0.3)

        y_true = tf.cast(y_true, tf.float32)
        y_pred = tf.clip_by_value(y_pred, epsilon, 1. - epsilon)
        pos_pred = tf.pow(-tf.log(y_pred), gamma)
        nag_pred = tf.pow(-tf.log(1 - y_pred), gamma)
        y_t = tf.multiply(y_true, pos_pred) + tf.multiply(1 - y_true, nag_pred)
        loss = tf.reduce_mean(y_t)

        return loss

    # Model definition
    def conv_block(in_x, nb_filter, kernel_size):
        x = layers.Conv1D(filters=nb_filter, kernel_size=kernel_size, padding='same')(in_x)
        x = layers.BatchNormalization()(x)
        x = layers.Activation(activation=relu)(x)
        return x

    def attention_branch(in_x, nb_filter, kernel_size):
        x1 = conv_block(in_x, nb_filter, kernel_size)

        x = layers.MaxPooling1D(pool_size=2)(x1)
        x = conv_block(x, nb_filter, kernel_size)
        x = layers.UpSampling1D(size=2)(x)

        x2 = conv_block(x, nb_filter, kernel_size)

        if (K.int_shape(x1) != K.int_shape(x2)):
            x2 = layers.ZeroPadding1D(padding=1)(x2)
            x2 = layers.Cropping1D((1, 0))(x2)

        x = layers.add([x1, x2])

        x = conv_block(x, nb_filter, kernel_size)

        x = layers.Conv1D(filters=nb_filter, kernel_size=1, padding='same')(x)
        x = layers.BatchNormalization()(x)
        x = layers.Activation(activation=sigmoid)(x)

        return x

    def RTA_block(in_x, nb_filter, kernel_size):
        x1 = conv_block(in_x, nb_filter, kernel_size)
        x2 = conv_block(x1, nb_filter, kernel_size)

        attention_map = attention_branch(x1, nb_filter, kernel_size)

        x = layers.multiply([x2, attention_map])
        x = layers.add([x, x1])

        out = conv_block(x, nb_filter, kernel_size)

        return out

    inp = __check_inputs(include_top, weights, input_tensor, input_shape, classes, classifier_activation)
    x = inp

    for fil, ker, pool in zip([16, 32, 64, 64],
                              [32, 16, 9, 9],
                              [4, 4, 2, 2]):
        x = RTA_block(x, fil, ker)
        x = layers.MaxPooling1D(pool)(x)

    x = layers.Dropout(0.6)(x)

    x = RTA_block(x, 128, 3)
    x = layers.MaxPooling1D(2)(x)
    x = RTA_block(x, 128, 3)
    x = layers.MaxPooling1D(2)(x)
    x = layers.Dropout(0.6)(x)

    if include_top:
        x = layers.Flatten()(x)
        x = layers.Dropout(rate=0.7)(x)
        x = layers.Dense(units=100, activation=relu)(x)
        x = layers.Dropout(rate=0.7)(x)
        x = layers.Dense(classes, activation=classifier_activation)(x)

    model = keras.Model(inputs=inp, outputs=x, name="YiboGao")

    if weights is not None:
        model.load_weights(weights)

    # Return the model and its custom loss function
    if return_loss:
        return model, en_loss
    else:
        return model