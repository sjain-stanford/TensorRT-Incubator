# SPDX-FileCopyrightText: Copyright (c) 2024 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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
from typing import Union
from tripy import constraints, export
from tripy.common.exception import raise_error
from tripy.frontend import utils as frontend_utils


@export.public_api(document_under="operations/functions")
@constraints.dtypes(
    constraints={"input": "T1", constraints.RETURN_VALUE: "T1"},
    variables={
        "T1": ["float32", "float16", "bfloat16", "int4", "float8", "int8", "int32", "int64", "bool"],
    },
)
@frontend_utils.process_dim
def repeat(input: "tripy.Tensor", repeats: Union[int, "tripy.ShapeScalar"], dim: int) -> "tripy.Tensor":
    """
    Repeats each element of a tensor after itself along the specified dimension.

    Args:
        input: The input tensor.
        repeats: The number of times to repeat each element.
        dim: The dimension along which to repeat values.

    Returns:
        The new tensor.

    .. code-block:: python
        :linenos:
        :caption: 1D tensor

        inp = tp.arange(4, dtype=tp.int32)
        out0 = tp.repeat(inp, 2, dim=0)

        np_inp = np.from_dlpack(tp.copy(inp, device=tp.device("cpu"))) # doc: omit
        ref_out0 = np.repeat(np_inp, 2, 0) # doc: omit
        assert np.array_equal(ref_out0, np.from_dlpack(tp.copy(out0, device=tp.device("cpu"))))


    .. code-block:: python
        :linenos:
        :caption: 2D tensor

        inp = tp.reshape(tp.arange(4, dtype=tp.int32), (2, 2))
        out0 = tp.repeat(inp, 2, dim=0)
        out1 = tp.repeat(inp, 2, dim=1)

        np_inp = np.from_dlpack(tp.copy(inp, device=tp.device("cpu"))) # doc: omit
        ref_out0 = np.repeat(np_inp, 2, 0) # doc: omit
        assert np.array_equal(ref_out0, np.from_dlpack(tp.copy(out0, device=tp.device("cpu"))))

        ref_out1 = np.repeat(np_inp, 2, 1) # doc: omit
        assert np.array_equal(ref_out1, np.from_dlpack(tp.copy(out1, device=tp.device("cpu"))))
    """
    from tripy.frontend.trace.ops.expand import expand
    from tripy.frontend.trace.ops.reshape import reshape
    from tripy.frontend.trace.ops.unsqueeze import unsqueeze
    from tripy.frontend.tensor import Tensor
    from tripy.frontend.shape import ShapeScalar, Shape
    from tripy.frontend.trace.ops.concatenate import concatenate

    if isinstance(repeats, int):
        if repeats < 0:
            raise_error("`repeats` value must be non-negative.", [f"Got: repeats={repeats}."])
        repeats = ShapeScalar(repeats)

    # By constraining repeats to be a single integer, we can use a very
    # simple implementation for repeat.
    # Imagine we have:
    #   a = [1, 2]
    #   out = tp.repeat(a, 2, dim=0)
    #
    # We achieve this by:
    #
    # [1, 2] -> [[1],  -> [[1, 1],  -> [1, 1, 2, 2]
    #            [2],]     [2, 2],]
    #
    out = unsqueeze(input, dim + 1)
    out = expand(out, input.shape[: dim + 1] + Shape([repeats]) + input.shape[dim + 1 :])

    repeat_mask = [1] * input.rank
    repeat_mask[dim] = repeats
    new_shape = input.shape.multiply(Shape(repeat_mask))
    out = reshape(out, new_shape)
    return out
