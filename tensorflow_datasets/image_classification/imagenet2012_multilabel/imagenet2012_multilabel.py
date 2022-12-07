# coding=utf-8
# Copyright 2022 The TensorFlow Datasets Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Imagenet validation with multi-label annotations (http://proceedings.mlr.press/v119/shankar20c.html).
"""

import json
import os

import numpy as np
from tensorflow_datasets.core.utils.lazy_imports_utils import tensorflow as tf
from tensorflow_datasets.datasets.imagenet2012 import imagenet_common
import tensorflow_datasets.public_api as tfds

_DESCRIPTION = """\
This dataset contains ILSVRC-2012 (ImageNet) validation images annotated with
multi-class labels from
["Evaluating Machine Accuracy on ImageNet"](http://proceedings.mlr.press/v119/shankar20c/shankar20c.pdf),
ICML, 2020.  The multi-class labels were reviewed by a panel of experts
extensively trained in the intricacies of fine-grained class distinctions in the
ImageNet class hierarchy (see paper for more details).
Compared to the original labels, these expert-reviewed multi-class labels enable
a more semantically coherent evaluation of accuracy.

Version 3.0.0 of this dataset contains more corrected labels from
["When does dough become a bagel? Analyzing the remaining mistakes on ImageNet](https://arxiv.org/abs/2205.04596)
as well as the ImageNet-Major (ImageNet-M) 68-example split under 'imagenet-m'.

Only 20,000 of the 50,000 ImageNet validation images have multi-label
annotations.  The set of multi-labels was first generated by a testbed of 67
trained ImageNet models, and then each individual model prediction was manually
annotated by the experts as either `correct` (the label is correct for the
image),`wrong` (the label is incorrect for the image), or `unclear` (no
consensus was reached among the experts).

Additionally, during annotation, the expert panel identified a set of
*problematic images*. An image was problematic if it met any of the below
criteria:

  * The original ImageNet label (top-1 label) was incorrect or unclear
  * Image was a drawing, painting, sketch, cartoon, or computer-rendered
  * Image was excessively edited
  * Image had inappropriate content

The problematic images are included in this dataset but should be ignored when
computing multi-label accuracy. Additionally, since the initial set of 20,000
annotations is class-balanced, but the set of problematic images is not, we
recommend computing the per-class accuracies and then averaging them. We also
recommend counting a prediction as correct if it is marked as correct or unclear
(i.e., being lenient with the unclear labels).

One possible way of doing this is with the following NumPy code:

```python
import tensorflow_datasets as tfds

ds = tfds.load('imagenet2012_multilabel', split='validation')

# We assume that predictions is a dictionary from file_name to a class index between 0 and 999

num_correct_per_class = {}
num_images_per_class = {}

for example in ds:
    # We ignore all problematic images
    if example[‘is_problematic’].numpy():
        continue

    # The label of the image in ImageNet
    cur_class = example['original_label'].numpy()

    # If we haven't processed this class yet, set the counters to 0
    if cur_class not in num_correct_per_class:
        num_correct_per_class[cur_class] = 0
        assert cur_class not in num_images_per_class
        num_images_per_class[cur_class] = 0

    num_images_per_class[cur_class] += 1

    # Get the predictions for this image
    cur_pred = predictions[example['file_name'].numpy()]

    # We count a prediction as correct if it is marked as correct or unclear
    # (i.e., we are lenient with the unclear labels)
    if cur_pred is in example['correct_multi_labels'].numpy() or cur_pred is in example['unclear_multi_labels'].numpy():
        num_correct_per_class[cur_class] += 1

# Check that we have collected accuracy data for each of the 1,000 classes
num_classes = 1000
assert len(num_correct_per_class) == num_classes
assert len(num_images_per_class) == num_classes

# Compute the per-class accuracies and then average them
final_avg = 0
for cid in range(num_classes):
  assert cid in num_correct_per_class
  assert cid in num_images_per_class
  final_avg += num_correct_per_class[cid] / num_images_per_class[cid]
final_avg /= num_classes

```
"""

_CITATION = """\
@article{shankar2019evaluating,
  title={Evaluating Machine Accuracy on ImageNet},
  author={Vaishaal Shankar* and Rebecca Roelofs* and Horia Mania and Alex Fang and Benjamin Recht and Ludwig Schmidt},
  journal={ICML},
  year={2020},
  note={\\url{http://proceedings.mlr.press/v119/shankar20c.html}}
}
@article{ImageNetChallenge,
  title={{ImageNet} large scale visual recognition challenge},
  author={Olga Russakovsky and Jia Deng and Hao Su and Jonathan Krause
   and Sanjeev Satheesh and Sean Ma and Zhiheng Huang and Andrej Karpathy and Aditya Khosla and Michael Bernstein and
   Alexander C. Berg and Fei-Fei Li},
  journal={International Journal of Computer Vision},
  year={2015},
  note={\\url{https://arxiv.org/abs/1409.0575}}
}
@inproceedings{ImageNet,
   author={Jia Deng and Wei Dong and Richard Socher and Li-Jia Li and Kai Li and Li Fei-Fei},
   booktitle={Conference on Computer Vision and Pattern Recognition (CVPR)},
   title={{ImageNet}: A large-scale hierarchical image database},
   year={2009},
   note={\\url{http://www.image-net.org/papers/imagenet_cvpr09.pdf}}
}
@article{vasudevan2022does,
  title={When does dough become a bagel? Analyzing the remaining mistakes on ImageNet},
  author={Vasudevan, Vijay and Caine, Benjamin and Gontijo-Lopes, Raphael and Fridovich-Keil, Sara and Roelofs, Rebecca},
  journal={arXiv preprint arXiv:2205.04596},
  year={2022}
}
"""

_MULTI_LABELS_URL = 'https://storage.googleapis.com/brain-car-datasets/imagenet-mistakes/human_accuracy_v3.0.0.json'


def _get_multi_labels_and_problematic_images(
    dl_manager: tfds.download.DownloadManager):
  """Returns multi-labels and problematic images from download json.

  Args:
    dl_manager: tfds.download.DownloadManager for downloading the json file

  Returns:
    val_annotated_images: Dictionary mapping image name to an inner dictionary
      containing the multi_label annotations for that image. The inner multi-
      label annotation dictionary has keys 'correct', 'wrong', or 'unclear'
      (keys will be missing if the image does not have a set of labels of the
      given type) and values that are lists of wnids.
    problematic_images: List of image names for problematic images.
    imagenet_m_2022:  List of image names comprising ImageNet-M 2022 evaluation
      slice.
  """
  with tf.io.gfile.GFile(dl_manager.download(_MULTI_LABELS_URL), 'r') as f:
    human_accuracy_data = json.load(f)
  val_annotated_images = {}
  prefix = 'ILSVRC2012_val_'
  len_prefix = len(prefix)
  for image_name in human_accuracy_data['initial_annots'].keys():
    if image_name[:len_prefix] == prefix:
      val_annotated_images[image_name] = human_accuracy_data['initial_annots'][
          image_name]

  problematic_images = list(human_accuracy_data['problematic_images'].keys())
  imagenet_m_2022 = human_accuracy_data['imagenet_m']
  return val_annotated_images, problematic_images, imagenet_m_2022


class Imagenet2012Multilabel(tfds.core.GeneratorBasedBuilder):
  """DatasetBuilder for imagenet2012_multilabel dataset."""

  VERSION = tfds.core.Version('3.0.0')
  RELEASE_NOTES = {
      '1.0.0': 'Initial release.',
      '2.0.0': 'Fixed ILSVRC2012_img_val.tar file.',
      '3.0.0': 'Corrected labels and ImageNet-M split.',
  }

  MANUAL_DOWNLOAD_INSTRUCTIONS = """\
  manual_dir should contain `ILSVRC2012_img_val.tar` file.
  You need to register on http://www.image-net.org/download-images in order
  to get the link to download the dataset.
  """

  def _info(self) -> tfds.core.DatasetInfo:
    """Returns the dataset metadata."""
    names_file = imagenet_common.label_names_file()
    return tfds.core.DatasetInfo(
        builder=self,
        description=_DESCRIPTION,
        features=tfds.features.FeaturesDict({
            'image':
                tfds.features.Image(encoding_format='jpeg'),
            'original_label':
                tfds.features.ClassLabel(names_file=names_file),
            'correct_multi_labels':
                tfds.features.Sequence(
                    tfds.features.ClassLabel(names_file=names_file)),
            'wrong_multi_labels':
                tfds.features.Sequence(
                    tfds.features.ClassLabel(names_file=names_file)),
            'unclear_multi_labels':
                tfds.features.Sequence(
                    tfds.features.ClassLabel(names_file=names_file)),
            'is_problematic':
                tfds.features.Tensor(shape=(), dtype=np.bool_),
            'file_name':
                tfds.features.Text(),
        }),
        supervised_keys=('image', 'correct_multi_labels'),
        homepage='https://github.com/modestyachts/evaluating_machine_accuracy_on_imagenet',
        citation=_CITATION,
    )

  def _split_generators(self, dl_manager: tfds.download.DownloadManager):
    """Returns SplitGenerators."""
    val_path = os.path.join(dl_manager.manual_dir, 'ILSVRC2012_img_val.tar')
    if not tf.io.gfile.exists(val_path):
      raise AssertionError(
          'ImageNet requires manual download of the data. Please download '
          'the train and val set and place them into: {}'.format(val_path))

    original_labels = imagenet_common.get_validation_labels(val_path)

    (multi_labels, problematic_images, imagenet_m_2022_errors
    ) = _get_multi_labels_and_problematic_images(dl_manager)

    imagenet_m_2022 = dict([(k, multi_labels[k]) for k in imagenet_m_2022_errors
                           ])

    return {
        'validation':
            self._generate_examples(
                archive=dl_manager.iter_archive(val_path),
                original_labels=original_labels,
                multi_labels=multi_labels,
                problematic_images=problematic_images),
        'imagenet_m':
            self._generate_examples(
                archive=dl_manager.iter_archive(val_path),
                original_labels=original_labels,
                multi_labels=imagenet_m_2022,
                problematic_images=problematic_images),
    }

  def _generate_examples(self, archive, original_labels, multi_labels,
                         problematic_images):
    """Yields (key, example) tuples from the dataset."""
    for fname, fobj in archive:
      if fname not in multi_labels:
        # Image is not in the annotated set of 20,000 images
        continue
      else:
        is_problematic = fname in problematic_images
        correct_multi_labels = []
        wrong_multi_labels = []
        unclear_multi_labels = []
        if 'correct' in multi_labels[fname]:
          correct_multi_labels = multi_labels[fname]['correct']
        if 'wrong' in multi_labels[fname]:
          wrong_multi_labels = multi_labels[fname]['wrong']
        if 'unclear' in multi_labels[fname]:
          unclear_multi_labels = multi_labels[fname]['unclear']

      record = {
          'file_name': fname,
          'image': fobj,
          'original_label': original_labels[fname],
          'correct_multi_labels': correct_multi_labels,
          'wrong_multi_labels': wrong_multi_labels,
          'unclear_multi_labels': unclear_multi_labels,
          'is_problematic': is_problematic
      }
      yield fname, record
