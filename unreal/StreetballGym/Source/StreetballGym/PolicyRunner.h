#pragma once

#include "CoreMinimal.h"
#include "UObject/Object.h"
#include "NNERuntimeCPU.h"
#include "PolicyRunner.generated.h"

class UNNEModelData;

/**
 * Plan B7: ONNX policy on the CPU through NNE (runtime "NNERuntimeORTCpu").
 * Input "obs" [1, NumObs] float32, output "action" [1, NumAction] float32.
 */
UCLASS()
class STREETBALLGYM_API UPolicyRunner : public UObject
{
	GENERATED_BODY()

public:
	/** Loads an .onnx file from disk (no asset import step needed). */
	bool LoadOnnx(const FString& Path, int32 InNumObs, int32 InNumAction, const FString& RuntimeName = TEXT("NNERuntimeORTCpu"));

	bool IsLoaded() const { return Instance.IsValid(); }

	/** Synchronous inference. Returns false if not loaded or the runtime failed. */
	bool Run(TConstArrayView<float> Obs, TArray<float>& OutAction);

	double LastInferenceMs = 0.0;
	int32 NumObs = 0;
	int32 NumAction = 0;

private:
	UPROPERTY() TObjectPtr<UNNEModelData> ModelData = nullptr;
	TSharedPtr<UE::NNE::IModelCPU> Model;
	TSharedPtr<UE::NNE::IModelInstanceCPU> Instance;
	TArray<float> InputBuf;
	TArray<float> OutputBuf;
};
