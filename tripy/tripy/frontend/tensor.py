#
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

from textwrap import indent
from typing import Any, Optional

import mlir_tensorrt.runtime.api as runtime

# Import ops to populate the registry before we define our Tensor class
import tripy.frontend.ops
import tripy.frontend.trace.ops
from tripy import export, utils
from tripy.backend.mlir import memref
from tripy.common import datatype
from tripy.common.exception import raise_error
from tripy.frontend.ops.registry import TENSOR_METHOD_REGISTRY
from tripy.frontend.trace.ops import Storage
from tripy.frontend.trace.tensor import TraceTensor
from tripy.utils.stack_info import StackInfo


class TensorMeta(type):
    def __new__(cls, name, bases, dct):
        new = type.__new__(cls, name, bases, dct)

        # We only register methods with the Tensor class. Derived classes
        # will inherit these methods normally. If we register for derived classes too
        # we run the risk of overwriting overridden methods.
        if name == "Tensor":
            # Add methods specified by individual ops to this class.
            for method_name in TENSOR_METHOD_REGISTRY:
                setattr(new, method_name, TENSOR_METHOD_REGISTRY[method_name])

        return new


@export.public_api(
    document_under="tensor/index.rst",
    autodoc_options=[
        ":special-members:",
        ":exclude-members: __init__, __repr__, __weakref__, __dlpack__, __dlpack_device__",
    ],
)
class Tensor(metaclass=TensorMeta):
    """
    A tensor is a multi-dimensional array that contains elements of a uniform data type.
    """

    _COUNT = 0

    # This field communicates to NumPy that it should allow our right-side operator overloads (e.g. __radd__) to take
    # precedence over its own left-side overloads (e.g. __add__). This will ensure that an expression of the form
    # `<np_array> <binary_op> Tensor` will return a Tensor and not a NumPy array.
    __array_priority__ = 10000

    @classmethod
    def _get_unique_name(cls):
        name = f"t{cls._COUNT}"
        cls._COUNT += 1
        return name

    def __init__(
        self,
        data: Any,
        dtype: Optional["tripy.dtype"] = None,
        device: Optional["tripy.device"] = None,
        name: Optional[str] = None,
        fetch_stack_info: bool = True,
    ) -> None:
        """
        Args:
            data: The data with which to initialize the tensor.
            dtype: The data type of the tensor.
            device: The device on which to allocate the tensor.
            name: The name of the tensor. If provided, this must be a unique string.
            fetch_stack_info: Whether to fetch stack information for the tensor.
                Stack information allows Tripy to generate much higher quality error
                messages at the cost of a small overhead when initializing the tensor.

        .. code-block:: python
            :linenos:
            :caption: Example

            tensor = tp.Tensor([1.0, 2.0, 3.0], dtype=tp.float32)
        """

        stack_info = StackInfo([])
        if fetch_stack_info:
            # We include code for everything above the `BaseTraceOp.build` function, which is called at most
            # this many stack frames above the constructor.
            STACK_DEPTH_OF_BUILD = 4
            stack_info = utils.get_stack_info(include_code_index=STACK_DEPTH_OF_BUILD)

        name = name if name is not None else Tensor._get_unique_name()

        self.trace_tensor = TraceTensor(name, stack_info, None, None, None, None)
        self.device = device

        # Note: It is important that we are able to call the Tensor constructor with no arguments
        # since this is used internally.
        if data is None:
            return

        if hasattr(data, "__dlpack__"):
            if not isinstance(data, runtime.MemRefValue):
                data = memref.create_memref_view(data)
            Storage.build_internal([], [self.trace_tensor], data)
        else:
            Storage.build_internal([], [self.trace_tensor], data, dtype, device)

        # Explicit cast if necessary
        # TODO(#155): Add copy as well when host allocation is fixed
        #             Also make device as a property, similar to dtype
        self.device = utils.default(device, self.trace_tensor.device)
        if dtype is not None and dtype != self.trace_tensor.dtype:
            from tripy.frontend.trace.ops.cast import cast

            self.trace_tensor = cast(self, dtype=dtype).trace_tensor

    def __getattr__(self, name: str):
        import tripy as tp
        from tripy.common.exception import search_for_missing_attr

        look_in = [(tp, "tripy")]
        search_for_missing_attr("tripy.Tensor", name, look_in)

    @property
    def name(self):
        return self.trace_tensor.name

    @name.setter
    def name(self, new_name):
        self.trace_tensor.name = new_name

    @property
    def stack_info(self):
        return self.trace_tensor.stack_info

    @stack_info.setter
    def stack_info(self, new_stack_info):
        self.trace_tensor.stack_info = new_stack_info

    @property
    def dtype(self):
        return self.trace_tensor.dtype

    @property
    def rank(self):
        return self.trace_tensor.rank

    def eval(self) -> runtime.MemRefValue:
        if isinstance(self.trace_tensor.producer, Storage) and self.trace_tensor.producer.has_memref:
            # Exit early if the tensor has already been evaluated.
            # This happens before the imports below so we don't incur extra overhead.
            return self.trace_tensor.producer.data

        from tripy.backend.mlir.compiler import Compiler
        from tripy.backend.mlir.executor import Executor
        from tripy.frontend.trace import Trace

        trace = Trace([self])
        flat_ir = trace.to_flat_ir()
        mlir = flat_ir.to_mlir()

        compiler = Compiler(trt_builder_opt_level=0)
        executable = compiler.compile(mlir, flat_ir=flat_ir)
        executor = Executor(executable)
        # Upon computing the value of this tensor, we switch it to have a `Storage`
        # parameter so that it does not need to be computed again.
        data = executor.execute([out.device for out in flat_ir.outputs])
        executor.stream.synchronize()
        assert len(data) == 1, "Expects only one output from mlir_tensorrt.compiler executor"
        data = data[0]
        # Data is present now. Assign the underlying device type.
        self.device = flat_ir.outputs[0].device

        Storage.build_internal([], [self.trace_tensor], data)
        self.trace_tensor.eval_stack_info = utils.get_stack_info()
        return data

    def tolist(self):
        data_memref = self.eval()
        if self.dtype not in (
            datatype.float32,
            datatype.int8,
            datatype.int32,
            datatype.int64,
            datatype.bool,
        ):
            from tripy.frontend.trace.ops.cast import cast

            data_memref = cast(Tensor(data_memref), datatype.float32).eval()
        return memref.tolist(data_memref)

    def __iter__(self):
        raise TypeError("Iterating over tensors is not supported")

    def __repr__(self) -> str:
        from tripy.frontend.utils import pretty_print

        data_list = self.tolist()
        data_shape = self.trace_tensor.producer.shape
        arr_str = pretty_print(data_list, data_shape)
        indentation = ""
        sep = ""
        if len(data_shape) > 1 and any(dim > 1 for dim in data_shape):
            indentation = " " * 4
            sep = "\n"
        return (
            f"tensor({sep}"
            f"{indent(arr_str, prefix=indentation)}, {sep}"
            f"{indent(f'dtype={self.dtype}, loc={self.device}, shape={data_shape}', prefix=indentation)}"
            f")"
        )

    # Since the underlying data is an MemRefValue we reuse their __dlpack__() and __dlpack_device__() methods
    def __dlpack__(self, stream: Any = None):
        return self.eval().__dlpack__()

    def __dlpack_device__(self):
        return self.eval().__dlpack_device__()

    def __bool__(self):
        data = self.tolist()
        if any(dim != 1 for dim in self.trace_tensor.producer.shape):
            raise_error(
                "Boolean value of a Tensor with more than one value is ambiguous",
                [f"Note: tensor shape was: {self.trace_tensor.producer.shape}"],
            )

        # Unwrap, since the item could be nested within a list. Without unwrapping, `[[[0]]]` returns True, when this should return False.
        for _ in range(self.rank):
            data = data[0]
        return bool(data)
