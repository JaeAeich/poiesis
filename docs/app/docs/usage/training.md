# Training Machine Learning Models with Poiesis

While TES is often used in genomics and data analysis pipelines,
**training machine learning models** is a natural extension—especially if you
have access to a GPU-enabled Kubernetes cluster. If your training job can be
described as “run this script on these inputs and save the outputs,”
then `Poiesis` fits right in.

Let’s walk through an example of training a simple CNN on the MNIST dataset
using **TensorFlow** via Poiesis.

## Step 1: Prepare the Training Script

First, upload your model training script to a data store that Poiesis can
access (such as MinIO).

Here's a minimal trainer script that:

- Loads the MNIST dataset
- Trains a small CNN
- Saves the trained model and performance metrics to disk

```python
import tensorflow as tf
from tensorflow.keras import layers, models
import json, os

output_dir = "mnist_cnn_output"
os.makedirs(output_dir, exist_ok=True)

(x_train, y_train), (x_test, y_test) = tf.keras.datasets.mnist.load_data()
x_train = x_train.astype("float32") / 255.0
x_test = x_test.astype("float32") / 255.0
x_train = x_train[..., tf.newaxis]
x_test = x_test[..., tf.newaxis]

y_train = tf.keras.utils.to_categorical(y_train, 10)
y_test = tf.keras.utils.to_categorical(y_test, 10)

model = models.Sequential([
    layers.Conv2D(32, (3, 3), activation='relu', input_shape=(28, 28, 1)),
    layers.MaxPooling2D((2, 2)),
    layers.Conv2D(64, (3, 3), activation='relu'),
    layers.MaxPooling2D((2, 2)),
    layers.Flatten(),
    layers.Dense(64, activation='relu'),
    layers.Dense(10, activation='softmax')
])

model.compile(optimizer='adam', loss='categorical_crossentropy', metrics=['accuracy'])

history = model.fit(x_train, y_train, epochs=5, batch_size=64, validation_split=0.1, verbose=0)
test_loss, test_acc = model.evaluate(x_test, y_test, verbose=2)

model.save(os.path.join(output_dir, "mnist_cnn_model.h5"))

metrics = {
    "test_loss": float(test_loss),
    "test_accuracy": float(test_acc),
    "history": {k: list(map(float, v)) for k, v in history.history.items()}
}

with open(os.path.join(output_dir, "metrics.json"), "w") as f:
    json.dump(metrics, f, indent=4)

print(f"Model and metrics saved to '{output_dir}'")
```

Upload the script to your object store:

```bash
mc cp model.py minio/poiesis/model_trainer/model_trainer.py
```

## Step 2: Submit the TES Task

Assuming your Poiesis server is running on `localhost:8000`, use the TES API to
launch a training task:

```bash
curl \
  -X POST http://localhost:8000/v1/tasks \
  -H "Authorization: Bearer asdf" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Model trainer",
    "description": "Train MNIST model using TensorFlow via TES",
    "inputs": [
    {
      "url": "s3://poiesis/model_trainer/model_trainer.py",
      "path": "/work/model_trainer.py",
      "type": "FILE"
    }
  ],
  "outputs": [
    {
      "url": "s3://poiesis/model",
      "path": "/work/mnist_cnn_output",
      "type": "DIRECTORY"
    }
  ],
  "resources": {
    "cpu_cores": 4,
    "ram_gb": 8,
    "disk_gb": 40
  },
  "executors": [
    {
      "image": "tensorflow/tensorflow",
      "command": [
        "python",
        "/work/model_trainer.py"
      ],
      "workdir": "/work"
    }
  ]
}'
```

This will execute the script in a container and store both the trained model
(`.h5`) and performance metrics (`metrics.json`) to MinIO.

## Step 3: Retrieve the Model

Once the task is complete, verify that your output files were saved:

```bash
mc ls minio/poiesis/model
```

You should see:

- `mnist_cnn_model.h5`
- `metrics.json`

You can now download and use the trained model for inference, evaluation, or fine-tuning.
