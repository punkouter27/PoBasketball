#include "PolicyRunner.h"
#include "StreetballGym.h"
#include "NNE.h"
#include "NNEModelData.h"
#include "NNERuntimeRunSync.h"
#include "NNETypes.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"

bool UPolicyRunner::LoadOnnx(const FString& Path, int32 InNumObs, int32 InNumAction, const FString& RuntimeName)
{
	Instance.Reset();
	Model.Reset();
	NumObs = InNumObs;
	NumAction = InNumAction;

	TArray<uint8> Bytes;
	if (!FFileHelper::LoadFileToArray(Bytes, *Path))
	{
		UE_LOG(LogStreetball, Error, TEXT("PolicyRunner: cannot read %s"), *Path);
		return false;
	}

	ModelData = NewObject<UNNEModelData>(this);
	ModelData->Init(TEXT("onnx"), Bytes);

	TWeakInterfacePtr<INNERuntimeCPU> Runtime = UE::NNE::GetRuntime<INNERuntimeCPU>(RuntimeName);
	if (!Runtime.IsValid())
	{
		UE_LOG(LogStreetball, Error, TEXT("PolicyRunner: NNE runtime '%s' not available. Runtimes: %s"),
			*RuntimeName, *FString::Join(UE::NNE::GetAllRuntimeNames(), TEXT(", ")));
		return false;
	}
	if (Runtime->CanCreateModelCPU(ModelData) != UE::NNE::EResultStatus::Ok)
	{
		UE_LOG(LogStreetball, Error, TEXT("PolicyRunner: runtime cannot create a CPU model from %s"), *Path);
		return false;
	}
	Model = Runtime->CreateModelCPU(ModelData);
	if (!Model.IsValid()) { UE_LOG(LogStreetball, Error, TEXT("PolicyRunner: CreateModelCPU failed")); return false; }
	Instance = Model->CreateModelInstanceCPU();
	if (!Instance.IsValid()) { UE_LOG(LogStreetball, Error, TEXT("PolicyRunner: CreateModelInstanceCPU failed")); return false; }

	const TConstArrayView<UE::NNE::FTensorDesc> InDescs = Instance->GetInputTensorDescs();
	const TConstArrayView<UE::NNE::FTensorDesc> OutDescs = Instance->GetOutputTensorDescs();
	if (InDescs.Num() != 1 || OutDescs.Num() != 1)
	{
		UE_LOG(LogStreetball, Error, TEXT("PolicyRunner: expected 1 input / 1 output, got %d / %d"), InDescs.Num(), OutDescs.Num());
		Instance.Reset();
		return false;
	}
	const uint32 Shape[2] = {1u, (uint32)NumObs};
	const UE::NNE::FTensorShape InShape = UE::NNE::FTensorShape::Make(Shape);
	if (Instance->SetInputTensorShapes({InShape}) != UE::NNE::EResultStatus::Ok)
	{
		UE_LOG(LogStreetball, Error, TEXT("PolicyRunner: SetInputTensorShapes([1,%d]) failed"), NumObs);
		Instance.Reset();
		return false;
	}
	const TConstArrayView<UE::NNE::FTensorShape> OutShapes = Instance->GetOutputTensorShapes();
	int32 OutVolume = 1;
	if (OutShapes.Num() == 1) { for (uint32 d : OutShapes[0].GetData()) OutVolume *= (int32)d; }
	if (OutVolume != NumAction)
	{
		UE_LOG(LogStreetball, Error, TEXT("PolicyRunner: output volume %d != %d"), OutVolume, NumAction);
		Instance.Reset();
		return false;
	}
	InputBuf.SetNumZeroed(NumObs);
	OutputBuf.SetNumZeroed(NumAction);
	UE_LOG(LogStreetball, Log, TEXT("PolicyRunner: loaded %s on %s (in '%s' [1,%d], out '%s' [1,%d])"),
		*Path, *RuntimeName, *InDescs[0].GetName(), NumObs, *OutDescs[0].GetName(), NumAction);
	return true;
}

bool UPolicyRunner::Run(TConstArrayView<float> Obs, TArray<float>& OutAction)
{
	if (!Instance.IsValid() || Obs.Num() != NumObs) return false;
	FMemory::Memcpy(InputBuf.GetData(), Obs.GetData(), NumObs * sizeof(float));
	UE::NNE::FTensorBindingCPU In{InputBuf.GetData(), (uint64)(NumObs * sizeof(float))};
	UE::NNE::FTensorBindingCPU Out{OutputBuf.GetData(), (uint64)(NumAction * sizeof(float))};
	const double T0 = FPlatformTime::Seconds();
	const UE::NNE::EResultStatus S = Instance->RunSync({In}, {Out});
	LastInferenceMs = (FPlatformTime::Seconds() - T0) * 1000.0;
	if (S != UE::NNE::EResultStatus::Ok) return false;
	if (OutAction.Num() != NumAction) OutAction.SetNumUninitialized(NumAction);   // first call only
	FMemory::Memcpy(OutAction.GetData(), OutputBuf.GetData(), NumAction * sizeof(float));
	return true;
}
