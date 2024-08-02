//===- ExecutorToExecutor.cpp ---------------------------------------------===//
//
// SPDX-FileCopyrightText: Copyright 2024 NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
// http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.
//
//===----------------------------------------------------------------------===//
///
/// Implementation of executor-to-executor lowerings.
///
//===----------------------------------------------------------------------===//
#include "mlir-executor/Executor/IR/Executor.h"
#include "mlir-executor/Conversion/ConvertToExecutorCommon.h"
#include "mlir-executor/Conversion/Passes.h"
#include "mlir/Dialect/Func/IR/FuncOps.h"
#include "mlir/IR/ImplicitLocOpBuilder.h"
#include "mlir/IR/PatternMatch.h"
#include "mlir/IR/TypeUtilities.h"
#include "mlir/Interfaces/DataLayoutInterfaces.h"
#include "mlir/Pass/Pass.h"
#include "mlir/Transforms/DialectConversion.h"
#include "llvm/ADT/STLExtras.h"
#include "llvm/ADT/SmallVectorExtras.h"
#include "llvm/ADT/StringExtras.h"

namespace mlir::executor {
#define GEN_PASS_DEF_CONVERTEXECUTORTOEXECUTORPASS
#include "mlir-executor/Conversion/Passes.h.inc"
} // namespace mlir::executor

using namespace mlir;
using namespace mlir::executor;

//===----------------------------------------------------------------------===//
// Executor-to-Executor Structural Conversions
//===----------------------------------------------------------------------===//

namespace {
/// Rewrite `executor.constant` if the type is illegal.
struct RewriteExecutorConst
    : public ConvertOpToExecutorPattern<executor::ConstantOp> {
  using ConvertOpToExecutorPattern::ConvertOpToExecutorPattern;
  LogicalResult
  matchAndRewrite(executor::ConstantOp op, OpAdaptor adaptor,
                  ConversionPatternRewriter &rewriter) const override {
    auto *typeConverter = getTypeConverter();
    Type resultType = typeConverter->convertType(op.getType());
    if (!resultType || resultType == op.getType())
      return failure();

    // We need to ensure that index type attributes are converted correctly.
    auto convertAttr = [&](Attribute val) -> Attribute {
      if (auto intAttr = dyn_cast<IntegerAttr>(val)) {
        return rewriter.getIntegerAttr(
            typeConverter->convertType(intAttr.getType()),
            intAttr.getValue().getSExtValue());
      };
      return val;
    };

    rewriter.replaceOpWithNewOp<executor::ConstantOp>(
        op, cast<TypedAttr>(convertAttr(adaptor.getValue())));
    return success();
  }
};

/// Structural conversion for the `executor.global` operation.
struct ConvertExecutorGlobalOp
    : public ConvertOpToExecutorPattern<executor::GlobalOp> {
  using ConvertOpToExecutorPattern::ConvertOpToExecutorPattern;
  LogicalResult
  matchAndRewrite(executor::GlobalOp op, OpAdaptor adaptor,
                  ConversionPatternRewriter &rewriter) const override {
    Type convertedType = typeConverter->convertType(op.getType());
    if (!convertedType || convertedType == op.getType())
      return failure();
    rewriter.modifyOpInPlace(op, [&]() { op.setType(convertedType); });
    return success();
  }
};

/// Convert `executor.func` by converting the function type signature using the
/// type converter.
struct ConvertExecutorFunc
    : public ConvertOpToExecutorPattern<executor::FuncOp> {
  using ConvertOpToExecutorPattern::ConvertOpToExecutorPattern;
  LogicalResult
  matchAndRewrite(executor::FuncOp op, OpAdaptor adaptor,
                  ConversionPatternRewriter &rewriter) const override {
    executor::ExecutorFunctionType oldType = op.getFunctionType();
    ExecutorTypeConverter::SignatureConversion conversion(
        oldType.getArgs().size());
    executor::ExecutorFunctionType newType =
        getTypeConverter()->convertExecutorFunctionSignature(oldType,
                                                             conversion);
    if (!newType || newType == oldType)
      return failure();
    auto newFuncOp =
        rewriter.create<executor::FuncOp>(op.getLoc(), op.getName(), newType);
    newFuncOp.setSymVisibilityAttr(op.getSymVisibilityAttr());
    rewriter.replaceOp(op, newFuncOp->getResults());
    return success();
  }
};
} // namespace

namespace {
/// Convert `executor.call`.
struct ConvertExecutorCall
    : public ConvertOpToExecutorPattern<executor::CallOp> {
  using ConvertOpToExecutorPattern::ConvertOpToExecutorPattern;
  LogicalResult
  matchAndRewrite(executor::CallOp op, OpAdaptor adaptor,
                  ConversionPatternRewriter &rewriter) const override {
    SmallVector<Type> resultTypes;
    if (failed(typeConverter->convertTypes(op->getResultTypes(), resultTypes)))
      return failure();

    ImplicitLocOpBuilder b(op.getLoc(), rewriter);
    SmallVector<Value> operands = convertFuncCallOperands(
        rewriter, op.getLoc(), op.getOperands(), adaptor.getOperands(),
        getTypeConverter()->getOptions().memrefArgPassingConvention);

    rewriter.replaceOpWithNewOp<executor::CallOp>(op, resultTypes,
                                                  op.getCallee(), operands);
    return success();
  }
};

/// Rewrite `executor` arithmetic ops if the types  are illegal.
struct LegalizeExecutorOperands
    : public OpInterfaceConversionPattern<executor::ExecutorOpInterface> {
  using OpInterfaceConversionPattern::OpInterfaceConversionPattern;
  LogicalResult
  matchAndRewrite(executor::ExecutorOpInterface op, ArrayRef<Value> operands,
                  ConversionPatternRewriter &rewriter) const override {
    if (isa<executor::ConstantOp, executor::FuncOp, executor::CallOp>(op) ||
        op->getNumRegions() > 0 ||
        (op->getNumResults() == 0 && op->getNumOperands() == 0))
      return failure();
    SmallVector<Type> resultTypes;
    if (failed(typeConverter->convertTypes(op->getResultTypes(), resultTypes)))
      return failure();
    OperationState state(op.getLoc(), op->getName(), operands, resultTypes,
                         llvm::to_vector(op->getAttrDictionary()));
    rewriter.replaceOp(op, rewriter.create(state)->getResults());
    return success();
  }
};

/// Convert operations that are 'lowerable to runtime builtin' to an
/// `executor.call` operation while also creating the `executor.func`
/// declaration if it does not already exist. This function assumes that the
/// desired function name is `executor_[op mnemonic]_[type1]_..._[typeN]` where
/// all types are simple scalar types.
struct LowerOpToBuiltin
    : public OpInterfaceConversionPattern<RuntimeBuiltinInterface> {

  LowerOpToBuiltin(ExecutorTypeConverter &typeConverter, MLIRContext *ctx,
                   PatternBenefit benefit = 1)
      : OpInterfaceConversionPattern(typeConverter, ctx, benefit),
        executorTypeConverter(typeConverter) {}

  LogicalResult
  matchAndRewrite(RuntimeBuiltinInterface op, ArrayRef<Value> operands,
                  ConversionPatternRewriter &rewriter) const override {
    mlir::ModuleOp moduleOp = op->getParentOfType<mlir::ModuleOp>();
    FailureOr<CallOpInterface> callOp =
        op.lowerToCall(operands, rewriter, moduleOp, *typeConverter,
                       executorTypeConverter.getDataLayout());
    if (failed(callOp))
      return failure();
    rewriter.replaceOp(op, *callOp);
    return success();
  }

  const ExecutorTypeConverter &executorTypeConverter;
};

/// Replace any op with `LowerToFuncCallTrait` with a `func.call` operation.
struct LowerToFuncCallTraitPattern
    : OpTraitConversionPattern<LowerToFuncCallTrait> {
  using OpTraitConversionPattern::OpTraitConversionPattern;

  LogicalResult
  matchAndRewrite(Operation *op, ArrayRef<Value> adaptor,
                  ConversionPatternRewriter &rewriter) const override {
    auto moduleOp = op->getParentOfType<ModuleOp>();
    if (!moduleOp)
      return failure();
    // For now just do simple substitution to get the name.
    std::string funcName =
        llvm::join(llvm::split(op->getName().getStringRef(), "."), "_");

    // Insert the declaration.
    SmallVector<Type> resultTypes;
    if (failed(getTypeConverter()->convertTypes(op->getResultTypes(),
                                                resultTypes)))
      return failure();

    mlir::SymbolRefAttr ref = [&] {
      auto *context = moduleOp.getContext();
      if (moduleOp.lookupSymbol<executor::FuncOp>(funcName))
        return SymbolRefAttr::get(context, funcName);

      // Insert the private function declaration into the body of the parent
      // module.
      OpBuilder::InsertionGuard g(rewriter);
      rewriter.setInsertionPointToStart(moduleOp.getBody());
      auto funcOp = rewriter.create<FuncOp>(
          op->getLoc(), funcName,
          ExecutorFunctionType::get(context,
                                    llvm::to_vector(TypeRange(adaptor)),
                                    resultTypes, UnitAttr{}));
      funcOp.setSymVisibility("private");
      return SymbolRefAttr::get(context, funcName);
    }();
    // Replace with call.
    rewriter.replaceOpWithNewOp<executor::CallOp>(
        op, resultTypes, ref.getLeafReference(), adaptor);
    return success();
  }
};

/// Loads of tables aren't converted to builtin calls. We must lower to a series
/// of loads and table creation.
struct LoadTableToTableCreate
    : public ConvertOpToExecutorPattern<executor::LoadOp> {
  using ConvertOpToExecutorPattern::ConvertOpToExecutorPattern;

  LogicalResult
  matchAndRewrite(executor::LoadOp op, OpAdaptor adaptor,
                  ConversionPatternRewriter &rewriter) const override {
    auto type = dyn_cast<TableType>(op.getType());
    if (!type)
      return failure();
    std::optional<uint64_t> bitWidth =
        getUniformWidthOfTableElements(type, getDataLayout());
    if (!bitWidth)
      return failure();

    SmallVector<Value> elements;
    elements.reserve(type.getBody().size());
    for (auto [idx, t] : llvm::enumerate(type.getBody())) {
      Value constant = rewriter.create<executor::ConstantOp>(
          op.getLoc(), rewriter.getIntegerAttr(adaptor.getOffset().getType(),
                                               (*bitWidth / 8) * idx));
      Value offset = rewriter.create<executor::AddIOp>(
          op.getLoc(), adaptor.getOffset(), constant);
      // constexpr uint64_t kBitsInByte = 8;
      Value integer = rewriter.create<executor::LoadOp>(
          op.getLoc(), t, adaptor.getPtr(), offset);
      elements.push_back(integer);
    }
    rewriter.replaceOpWithNewOp<CreateTableOp>(op, op.getType(), elements);
    return success();
  }
};

/// Handle conversion of ConstantResource attribute initializer values. This
/// should really only be invoked when the initializer value has "index" element
/// type , which needs to be converted to the target index type for
/// future serialization.
struct ConstantResourceConversionPattern
    : public ConvertOpToExecutorPattern<executor::ConstantResourceOp> {
  using ConvertOpToExecutorPattern::ConvertOpToExecutorPattern;

  LogicalResult
  matchAndRewrite(executor::ConstantResourceOp op, OpAdaptor adaptor,
                  ConversionPatternRewriter &rewriter) const override {
    auto attr = dyn_cast<DenseIntElementsAttr>(op.getValue());
    if (!attr ||
        typeConverter->isLegal(mlir::getElementTypeOrSelf(attr.getType())))
      return failure();

    Type srcType = attr.getType().getElementType();
    Type dstType = getTypeConverter()->convertType(srcType);
    assert(srcType != dstType && dstType.isSignlessInteger() &&
           "index type should be converted to a signless integer type");
    DenseElementsAttr newAttr = attr.mapValues(dstType, [&](const APInt &src) {
      return src.sextOrTrunc(dstType.getIntOrFloatBitWidth());
    });
    rewriter.modifyOpInPlace(op, [&]() { op.setValueAttr(newAttr); });
    return success();
  }
};
} // namespace

void executor::populateExecutorDialectLegality(
    ExecutorTypeConverter &typeConverter, ConversionTarget &target) {}

void executor::populateExecutorStructuralConversionPatternsAndLegality(
    RewritePatternSet &patterns, ExecutorTypeConverter &typeConverter,
    ConversionTarget &target) {
  target.addDynamicallyLegalDialect<executor::ExecutorDialect>(
      [&](Operation *op) {
        if (auto funcOp = dyn_cast<executor::FuncOp>(op)) {
          auto type = funcOp.getFunctionType();
          return typeConverter.isLegal(type.getArgs()) &&
                 typeConverter.isLegal(type.getResults());
        }
        if (auto globalOp = dyn_cast<executor::GlobalOp>(op))
          return typeConverter.isLegal(globalOp.getType());

        if (auto constantResourceOp = dyn_cast<ConstantResourceOp>(op))
          return typeConverter.isLegal(mlir::getElementTypeOrSelf(
              constantResourceOp.getValue().getType()));

        if (isa<RuntimeBuiltinInterface>(op))
          return false;

        if (op->hasTrait<executor::LowerToFuncCallTrait>())
          return false;

        return typeConverter.isLegal(op->getOperandTypes()) &&
               typeConverter.isLegal(op->getResultTypes());
      });

  // TODO: move more func lowerings from `executor-expand-ops` to here.
  patterns.add<RewriteExecutorConst, LegalizeExecutorOperands,
               ConvertExecutorGlobalOp, ConvertExecutorFunc,
               ConvertExecutorCall, ConstantResourceConversionPattern>(
      typeConverter, patterns.getContext());
  patterns.add<LowerOpToBuiltin, LowerToFuncCallTraitPattern,
               LoadTableToTableCreate>(typeConverter, patterns.getContext());
}

static LogicalResult convertExecutorFunctionMetadataAttrs(
    Operation *module, const ExecutorTypeConverter &typeConverter) {
  // Convert any `executor.function_metadata` attributes on the function
  // types.
  SmallVector<func::FuncOp> funcs;
  module->walk([&](func::FuncOp func) {
    if (!func->hasAttr(ExecutorDialect::kFunctionMetadataAttrName))
      return;
    funcs.push_back(func);
  });

  // Converts the type in the metadata signature. We allow most types
  // since they can carry important high-level information. But we disallow
  // 'index type', since we expect the backend to be specialized to i32 or i64.
  auto convertType = [&](Type t) -> Type {
    if (isa<IndexType>(t))
      return typeConverter.getIndexType();
    if (isa<MemRefType>(t)) {
      auto mT = llvm::cast<MemRefType>(t);
      if (llvm::isa<IndexType>(mT.getElementType())) {
        return MemRefType::get(mT.getShape(), typeConverter.getIndexType(),
                               mT.getLayout(), mT.getMemorySpace());
      }
    }
    return t;
  };

  for (func::FuncOp func : funcs) {
    auto metadata = func->getAttrOfType<FunctionMetadataAttr>(
        ExecutorDialect::kFunctionMetadataAttrName);
    SmallVector<Type> argTypes =
        llvm::map_to_vector(metadata.getArgs(), convertType);
    SmallVector<Type> resultTypes =
        llvm::map_to_vector(metadata.getResults(), convertType);

    auto attr = FunctionMetadataAttr::get(
        module->getContext(), argTypes, resultTypes,
        metadata.getNumOutputArgs(), metadata.getArgBounds(),
        metadata.getResultBounds(), metadata.getShapeFunc(),
        metadata.getCconv());

    func->setAttr(ExecutorDialect::kFunctionMetadataAttrName, attr);
  }

  return success();
}

namespace {
/// Pass to convert `executor` to `executor` dialect operations.
class ConvertExecutorToExecutorPass
    : public mlir::executor::impl::ConvertExecutorToExecutorPassBase<
          ConvertExecutorToExecutorPass> {
public:
  using Base::Base;
  void runOnOperation() override {
    MLIRContext *ctx = &getContext();
    ConversionTarget target(*ctx);
    LowerToExecutorOptions opts;
    opts.indexType = IntegerType::get(ctx, indexBitwidth);
    opts.memrefArgPassingConvention =
        usePackedMemRefCConv ? executor::MemRefArgPassingConvention::Packed
                             : executor::MemRefArgPassingConvention::Unpacked;
    Operation *op = getOperation();
    FailureOr<DataLayout> dataLayout =
        executor::setDataLayoutSpec(op, indexBitwidth, 64);
    if (failed(dataLayout)) {
      emitError(op->getLoc())
          << "failed to set DataLayout; op has DLTI spec that is "
             "inconsistent with provided options";
      return signalPassFailure();
    }
    ExecutorTypeConverter typeConverter(ctx, opts, std::move(*dataLayout));
    RewritePatternSet patterns(ctx);
    executor::populateExecutorStructuralConversionPatternsAndLegality(
        patterns, typeConverter, target);

    if (failed(applyPartialConversion(getOperation(), target,
                                      std::move(patterns))))
      return signalPassFailure();

    if (failed(convertExecutorFunctionMetadataAttrs(op, typeConverter)))
      return signalPassFailure();
  }
};
} // namespace
