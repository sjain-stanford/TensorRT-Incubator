#
# SPDX-FileCopyrightText: Copyright (c) 1993-2024 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

import math
import numbers
from typing import Optional, Sequence, Union

from tripy import export
from tripy.common import datatype
from tripy.common.exception import raise_error
from tripy.frontend.trace.ops.fill import full, full_like
from tripy.frontend.trace.ops.iota import iota, iota_like
from tripy.frontend.trace.ops.where import where
from tripy.frontend import utils as frontend_utils


@export.public_api(document_under="tensor_operations")
@frontend_utils.convert_inputs_to_tensors(shape_argument=["shape"], exclude=["dtype"])
def ones(
    shape: Union["tripy.Shape", Sequence[Union[int, "tripy.Tensor"]]],
    dtype: datatype.dtype = datatype.float32,
) -> "tripy.Tensor":
    """
    Creates a Tensor of the specified shape and dtype with all elements set to 1.

    Args:
        shape: The desired shape of the tensor.
        dtype: Datatype of elements.

    Returns:
        A tensor of shape ``shape`` with all elements set to 1.

    .. code-block:: python
        :linenos:
        :caption: Example

        output = tp.ones([2, 3])

        assert np.array_equal(cp.from_dlpack(output).get(), np.ones([2, 3], dtype=np.float32))

    .. seealso:: :func:`ones_like`, :func:`full`
    """
    return full(shape, 1, dtype)


@export.public_api(document_under="tensor_operations")
@frontend_utils.convert_inputs_to_tensors(shape_argument=["shape"], exclude=["dtype"])
def zeros(
    shape: Union["tripy.Shape", Sequence[Union[int, "tripy.Tensor"]]],
    dtype: datatype.dtype = datatype.float32,
) -> "tripy.Tensor":
    """
    Creates a Tensor of the specified shape and dtype with all elements set to 0.

    Args:
        shape: The desired shape of the tensor.
        dtype: Datatype of elements.

    Returns:
        A tensor of shape ``shape`` with all elements set to 0.

    .. code-block:: python
        :linenos:
        :caption: Example

        output = tp.zeros([2, 3])

        assert np.array_equal(cp.from_dlpack(output).get(), np.zeros([2, 3], dtype=np.float32))

    .. seealso:: :func:`zeros_like`, :func:`full`
    """
    return full(shape, 0, dtype)


@export.public_api(document_under="tensor_operations")
def ones_like(input: "tripy.Tensor", dtype: Optional[datatype.dtype] = None) -> "tripy.Tensor":
    """
    Creates a tensor with all elements set to 1 of the same shape as the input tensor.

    Args:
        input: The input tensor.
        dtype: Datatype of elements. If set to ``None``, the datatype of the input tensor is used.

    Returns:
        A tensor of the same shape as the input with all elements set to 1.

    .. code-block:: python
        :linenos:
        :caption: Example

        input = tp.zeros([2, 3], dtype=tp.float32)
        output = tp.ones_like(input)

        assert np.array_equal(cp.from_dlpack(output).get(), np.ones([2, 3], dtype=np.float32))

    .. seealso:: :func:`ones`, :func:`full_like`
    """
    return full_like(input, 1, dtype)


@export.public_api(document_under="tensor_operations")
def zeros_like(input: "tripy.Tensor", dtype: Optional[datatype.dtype] = None) -> "tripy.Tensor":
    """
    Creates a Tensor with all elements set to 0 of the same shape as the input tensor.

    Args:
        input: The input tensor.
        dtype: Datatype of elements. If set to ``None``, the datatype of the input tensor is used.

    Returns:
        A tensor of the same shape as the input with all elements set to 0.

    .. code-block:: python
        :linenos:
        :caption: Example

        input = tp.iota([2, 3], dtype=tp.float32)
        output = tp.zeros_like(input)

        assert np.array_equal(cp.from_dlpack(output).get(), np.zeros([2, 3], dtype=np.float32))

    .. seealso:: :func:`zeros`, :func:`full_like`
    """

    return full_like(input, 0, dtype)


@export.public_api(document_under="tensor_operations")
def tril(tensor: "tripy.Tensor", diagonal: int = 0) -> "tripy.Tensor":
    r"""
    Returns the lower triangular part of each :math:`[M, N]` matrix in the tensor, with all other elements set to 0.
    If the tensor has more than two dimensions, it is treated as a batch of matrices.

    Args:
        tensor: The tripy tensor to operate on.
        diagonal: The diagonal above which to zero elements.
            ``diagonal=0`` indicates the main diagonal which is defined by the set of indices
            :math:`{{(i, i)}}` where :math:`i \in [0, min(M, N))`.

            Positive values indicate the diagonal which is that many diagonals above the main one,
            while negative values indicate one which is below.

    Returns:
        A tensor of the same shape and datatype as this tensor.

    .. code-block:: python
        :linenos:
        :caption: Main Diagonal

        input = tp.iota((5, 5)) + 1.
        output = tp.tril(input)

        assert np.array_equal(cp.from_dlpack(output).get(), np.tril(cp.from_dlpack(input).get()))

    .. code-block:: python
        :linenos:
        :caption: Two Diagonals Above Main

        input = tp.iota((5, 5)) + 1. # doc: omit
        output = tp.tril(input, diagonal=2)

        assert np.array_equal(cp.from_dlpack(output).get(), np.tril(cp.from_dlpack(input).get(), 2))

    .. code-block:: python
        :linenos:
        :caption: One Diagonal Below Main

        input = tp.iota((5, 5)) + 1. # doc: omit
        output = tp.tril(input, diagonal=-1)

        assert np.array_equal(cp.from_dlpack(output).get(), np.tril(cp.from_dlpack(input).get(), -1))
    """
    tri_mask = (iota_like(tensor, 0, datatype.int32) + full_like(tensor, diagonal, datatype.int32)) >= iota_like(
        tensor, 1, datatype.int32
    )
    zeros_tensor = zeros_like(tensor)
    return where(tri_mask, tensor, zeros_tensor)


@export.public_api(document_under="tensor_operations")
def triu(tensor: "tripy.Tensor", diagonal: int = 0) -> "tripy.Tensor":
    r"""
    Returns the upper triangular part of each :math:`[M, N]` matrix in the tensor, with all other elements set to 0.
    If the tensor has more than two dimensions, it is treated as a batch of matrices.

    Args:
        tensor: The tripy tensor to operate on.
        diagonal: The diagonal below which to zero elements.
            ``diagonal=0`` indicates the main diagonal which is defined by the set of indices
            :math:`{{(i, i)}}` where :math:`i \in [0, min(M, N))`.

            Positive values indicate the diagonal which is that many diagonals above the main one,
            while negative values indicate one which is below.

    Returns:
        A tensor of the same shape and datatype as this tensor.

    .. code-block:: python
        :linenos:
        :caption: Main Diagonal

        input = tp.iota((5, 5)) + 1.
        output = tp.triu(input)

        assert np.array_equal(cp.from_dlpack(output).get(), np.triu(cp.from_dlpack(input).get()))

    .. code-block:: python
        :linenos:
        :caption: Two Diagonals Above Main

        input = tp.iota((5, 5)) + 1. # doc: omit
        output = tp.triu(input, diagonal=2)

        assert np.array_equal(cp.from_dlpack(output).get(), np.triu(cp.from_dlpack(input).get(), 2))

    .. code-block:: python
        :linenos:
        :caption: One Diagonal Below Main

        input = tp.iota((5, 5)) + 1. # doc: omit
        output = tp.triu(input, diagonal=-1)

        assert np.array_equal(cp.from_dlpack(output).get(), np.triu(cp.from_dlpack(input).get(), -1))
    """
    tri_mask = (iota_like(tensor, 0, datatype.int32) + full_like(tensor, diagonal, datatype.int32)) <= iota_like(
        tensor, 1, datatype.int32
    )
    zeros_tensor = zeros_like(tensor)
    return where(tri_mask, tensor, zeros_tensor)


@export.public_api(document_under="tensor_operations")
def arange(
    start: numbers.Number, stop: numbers.Number, step: numbers.Number = 1, dtype: "tripy.dtype" = datatype.float32
) -> "tripy.Tensor":
    r"""
    Returns a 1D tensor containing a sequence of numbers in the half-open interval
    :math:`[0, \text{stop})` incrementing by :math:`\text{step}`.

    Args:
        start: The inclusive lower bound of the values to generate.
        stop: The exclusive upper bound of the values to generate.
        step: The spacing between values.
        dtype: The desired datatype of the tensor.

    Returns:
        A tensor of shape :math:`[\frac{\text{stop}-\text{start}}{\text{step}}]`.

    .. code-block:: python
        :linenos:
        :caption: Example

        output = tp.arange(0.5, 2.5)

        assert (cp.from_dlpack(output).get() == np.arange(0.5, 2.5, dtype=np.float32)).all()

    .. code-block:: python
        :linenos:
        :caption: Custom ``step`` Value

        output = tp.arange(2.3, 0.8, -0.2)

        assert np.allclose(cp.from_dlpack(output).get(), np.arange(2.3, 0.8, -0.2, dtype=np.float32))
    """
    if step == 0:
        raise_error("Step in arange cannot be 0.", [])

    size = math.ceil((stop - start) / step)
    if size <= 0:
        raise_error(
            "Arange tensor is empty.",
            details=[
                f"start={start}, stop={stop}, step={step}",
            ],
        )
    output = iota((size,), 0, dtype) * full((size,), step, dtype) + full((size,), start, dtype)
    return output


@export.public_api(document_under="tensor_operations")
def arange(stop: numbers.Number, dtype: "tripy.dtype" = datatype.float32) -> "tripy.Tensor":
    r"""
    Returns a 1D tensor containing a sequence of numbers in the half-open interval
    :math:`[0, \text{stop})` incrementing by 1.


    Args:
        stop: The exclusive upper bound of the values to generate.
        dtype: The desired datatype of the tensor.

    Returns:
        A tensor of shape :math:`[\text{stop}]`.

    .. code-block:: python
        :linenos:
        :caption: Example

        output = tp.arange(5)

        assert (cp.from_dlpack(output).get() == np.arange(5, dtype=np.float32)).all()
    """
    return arange(0, stop, dtype=dtype)