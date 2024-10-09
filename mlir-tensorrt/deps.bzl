# Licensed under the Apache License v2.0 with LLVM Exceptions.
# See https://llvm.org/LICENSE.txt for license information.
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
# Also available under a BSD-style license. See LICENSE.

load("@bazel_tools//tools/build_defs/repo:http.bzl", "http_archive")

def third_party_deps():
    LLVM_COMMIT = "c8b5d30f707757a4fe4d9d0bb01f762665f6942f"
    LLVM_SHA256 = "2f45df5b22f3b9db8080bd67899158cf040b4d3fbff3a049cfe1979313e51638"
    http_archive(
        name = "llvm-raw",
        build_file_content = "# empty",
        sha256 = LLVM_SHA256,
        strip_prefix = "llvm-project-" + LLVM_COMMIT,
        urls = ["https://github.com/llvm/llvm-project/archive/{commit}.tar.gz".format(commit = LLVM_COMMIT)],
    )

    SKYLIB_VERSION = "1.3.0"
    http_archive(
        name = "bazel_skylib",
        sha256 = "74d544d96f4a5bb630d465ca8bbcfe231e3594e5aae57e1edbf17a6eb3ca2506",
        urls = [
            "https://mirror.bazel.build/github.com/bazelbuild/bazel-skylib/releases/download/{version}/bazel-skylib-{version}.tar.gz".format(version = SKYLIB_VERSION),
            "https://github.com/bazelbuild/bazel-skylib/releases/download/{version}/bazel-skylib-{version}.tar.gz".format(version = SKYLIB_VERSION),
        ],
    )

    http_archive(
        name = "llvm_zstd",
        build_file = "@llvm-raw//utils/bazel/third_party_build:zstd.BUILD",
        sha256 = "7c42d56fac126929a6a85dbc73ff1db2411d04f104fae9bdea51305663a83fd0",
        strip_prefix = "zstd-1.5.2",
        urls = [
            "https://github.com/facebook/zstd/releases/download/v1.5.2/zstd-1.5.2.tar.gz",
        ],
    )

    http_archive(
        name = "llvm_zlib",
        build_file = "@llvm-raw//utils/bazel/third_party_build:zlib-ng.BUILD",
        sha256 = "e36bb346c00472a1f9ff2a0a4643e590a254be6379da7cddd9daeb9a7f296731",
        strip_prefix = "zlib-ng-2.0.7",
        urls = [
            "https://github.com/zlib-ng/zlib-ng/archive/refs/tags/2.0.7.zip",
        ],
    )

    http_archive(
        name = "tensorrt10_x86",
        build_file = "//:third_party/tensorrt10_x86.BUILD",
        sha256 = "885ba84087d9633e07cdaf76b022a99c7460fbe42b487cabec6524409af2591b",
        strip_prefix = "TensorRT-10.2.0.19",
        url = "https://developer.nvidia.com/downloads/compute/machine-learning/tensorrt/10.2.0/tars/TensorRT-10.2.0.19.Linux.x86_64-gnu.cuda-12.5.tar.gz",
    )

    # TODO: figure out how to get cuda deps working
    # RULES_CUDA_COMMIT = "a3e87114b41f78373f916ce1021183943c6057e9"
    # RULES_CUDA_SHA256 = "eb40d2ecabbd4dac8c13534cd3b97d7f9c8fb4aa2ae8bf6c1cc2c8b31bfaede9"
    # http_archive(
    #     name = "rules_cuda",
    #     sha256 = RULES_CUDA_SHA256,
    #     strip_prefix = "rules_cuda-" + RULES_CUDA_COMMIT,
    #     urls = ["https://github.com/bazel-contrib/rules_cuda/archive/{commit}.tar.gz".format(commit = RULES_CUDA_COMMIT)],
    # )