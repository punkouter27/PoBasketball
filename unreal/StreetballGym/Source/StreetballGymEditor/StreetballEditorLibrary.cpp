#include "StreetballEditorLibrary.h"

#include "ClothingAsset.h"
#include "ClothingAssetFactoryInterface.h"
#include "ClothingSystemEditorInterfaceModule.h"
#include "ChaosCloth/ChaosClothConfig.h"
#include "Engine/SkeletalMesh.h"
#include "Modules/ModuleManager.h"
#include "NiagaraEmitterHandle.h"
#include "NiagaraSystem.h"
#include "PointWeightMap.h"
#include "UObject/UObjectHash.h"
#include "Materials/Material.h"
#include "MaterialShared.h"
#include "ShaderCompiler.h"
#include "RHIShaderPlatform.h"

DEFINE_LOG_CATEGORY_STATIC(LogStreetballEditor, Log, All);

namespace
{
	/** Walk "A.B.C" through struct members (and object pointers) and return the final property + its container. */
	bool ResolvePath(UObject* Obj, const FString& Path, FProperty*& OutProp, void*& OutContainer, UObject*& OutOwner)
	{
		TArray<FString> Parts;
		Path.ParseIntoArray(Parts, TEXT("."));
		if (!Obj || Parts.Num() == 0) return false;
		UStruct* Struct = Obj->GetClass();
		void* Container = Obj;
		OutOwner = Obj;
		for (int32 i = 0; i < Parts.Num(); ++i)
		{
			FProperty* Prop = Struct->FindPropertyByName(FName(*Parts[i]));
			if (!Prop) return false;
			if (i == Parts.Num() - 1)
			{
				OutProp = Prop;
				OutContainer = Container;
				return true;
			}
			if (FStructProperty* SP = CastField<FStructProperty>(Prop))
			{
				Container = SP->ContainerPtrToValuePtr<void>(Container);
				Struct = SP->Struct;
			}
			else if (FObjectPropertyBase* OP = CastField<FObjectPropertyBase>(Prop))
			{
				UObject* Inner = OP->GetObjectPropertyValue_InContainer(Container);
				if (!Inner) return false;
				Container = Inner;
				Struct = Inner->GetClass();
				OutOwner = Inner;
			}
			else
			{
				return false;
			}
		}
		return false;
	}
}

FString UStreetballEditorLibrary::DescribeObject(UObject* Obj)
{
	if (!Obj) return TEXT("<null>");
	FString Out = FString::Printf(TEXT("%s (%s)\n"), *Obj->GetPathName(), *Obj->GetClass()->GetName());
	for (TFieldIterator<FProperty> It(Obj->GetClass()); It; ++It)
	{
		FString Value;
		It->ExportTextItem_InContainer(Value, Obj, nullptr, Obj, PPF_None);
		if (Value.Len() > 400) Value = Value.Left(400) + TEXT("...");
		Out += FString::Printf(TEXT("  %s : %s = %s\n"), *It->GetName(), *It->GetCPPType(), *Value);
	}
	return Out;
}

TArray<UObject*> UStreetballEditorLibrary::GetInnerObjects(UObject* Outer)
{
	TArray<UObject*> Out;
	if (Outer) GetObjectsWithOuter(Outer, Out, EGetObjectsFlags::None);
	return Out;
}

bool UStreetballEditorLibrary::SetPropertyText(UObject* Obj, const FString& Path, const FString& Value)
{
	FProperty* Prop = nullptr; void* Container = nullptr; UObject* Owner = nullptr;
	if (!ResolvePath(Obj, Path, Prop, Container, Owner))
	{
		UE_LOG(LogStreetballEditor, Warning, TEXT("SetPropertyText: %s has no property path %s"), Obj ? *Obj->GetName() : TEXT("null"), *Path);
		return false;
	}
	Owner->PreEditChange(Prop);
	void* ValuePtr = Prop->ContainerPtrToValuePtr<void>(Container);
	const TCHAR* Result = Prop->ImportText_Direct(*Value, ValuePtr, Owner, PPF_None);
	FPropertyChangedEvent Evt(Prop, EPropertyChangeType::ValueSet);
	Owner->PostEditChangeProperty(Evt);
	if (Owner != Obj)
	{
		Obj->PostEditChange();
	}
	Owner->MarkPackageDirty();
	if (!Result)
	{
		UE_LOG(LogStreetballEditor, Warning, TEXT("SetPropertyText: could not parse '%s' for %s.%s"), *Value, *Obj->GetName(), *Path);
		return false;
	}
	return true;
}

FString UStreetballEditorLibrary::GetPropertyText(UObject* Obj, const FString& Path)
{
	FProperty* Prop = nullptr; void* Container = nullptr; UObject* Owner = nullptr;
	if (!ResolvePath(Obj, Path, Prop, Container, Owner)) return FString();
	FString Value;
	Prop->ExportTextItem_InContainer(Value, Container, nullptr, Owner, PPF_None);
	return Value;
}

bool UStreetballEditorLibrary::SetNiagaraEmitterEnabled(UNiagaraSystem* System, const FString& EmitterName, bool bEnabled)
{
	if (!System) return false;
	for (FNiagaraEmitterHandle& H : System->GetEmitterHandles())
	{
		if (H.GetName().ToString() == EmitterName)
		{
			H.SetIsEnabled(bEnabled, *System, false);
			System->MarkPackageDirty();
			return true;
		}
	}
	return false;
}

TArray<FString> UStreetballEditorLibrary::GetNiagaraEmitterNames(UNiagaraSystem* System)
{
	TArray<FString> Out;
	if (!System) return Out;
	for (const FNiagaraEmitterHandle& H : System->GetEmitterHandles())
	{
		Out.Add(FString::Printf(TEXT("%s%s"), *H.GetName().ToString(), H.GetIsEnabled() ? TEXT("") : TEXT(" (disabled)")));
	}
	return Out;
}

bool UStreetballEditorLibrary::CompileNiagaraSystem(UNiagaraSystem* System)
{
	if (!System) return false;
	System->RequestCompile(false);
	System->WaitForCompilationComplete();
	System->MarkPackageDirty();
	return true;
}

UObject* UStreetballEditorLibrary::CreateClothFromSection(USkeletalMesh* Mesh, int32 LodIndex, int32 SectionIndex, float MaxDistanceCm, float PinFraction, const FString& AssetName)
{
	if (!Mesh) return nullptr;
	FClothingSystemEditorInterfaceModule& ClothModule = FModuleManager::LoadModuleChecked<FClothingSystemEditorInterfaceModule>(TEXT("ClothingSystemEditorInterface"));
	UClothingAssetFactoryBase* Factory = ClothModule.GetClothingAssetFactory();
	if (!Factory) return nullptr;

	FSkeletalMeshClothBuildParams Params;
	Params.AssetName = AssetName;
	Params.LodIndex = LodIndex;
	Params.SourceSection = SectionIndex;
	Params.bRemoveFromMesh = false;
	UClothingAssetCommon* Cloth = Cast<UClothingAssetCommon>(Factory->CreateFromSkeletalMesh(Mesh, Params));
	if (!Cloth || Cloth->LodData.Num() == 0)
	{
		UE_LOG(LogStreetballEditor, Error, TEXT("CreateClothFromSection: factory failed for %s section %d"), *Mesh->GetName(), SectionIndex);
		return nullptr;
	}

	// Max Distance from height: pinned band at the top, free hem at the bottom (smooth ramp).
	FClothLODDataCommon& Lod = Cloth->LodData[0];
	const TArray<FVector3f>& V = Lod.PhysicalMeshData.Vertices;
	float ZMin = TNumericLimits<float>::Max(), ZMax = TNumericLimits<float>::Lowest();
	for (const FVector3f& P : V) { ZMin = FMath::Min(ZMin, P.Z); ZMax = FMath::Max(ZMax, P.Z); }
	const float Span = FMath::Max(ZMax - ZMin, 1.f);
	const float PinZ = ZMax - PinFraction * Span;
	FPointWeightMap* Map = nullptr;
	for (FPointWeightMap& M : Lod.PointWeightMaps)
	{
		if (M.CurrentTarget == (uint8)EWeightMapTargetCommon::MaxDistance) { Map = &M; break; }
	}
	if (!Map)
	{
		Map = &Lod.PointWeightMaps.AddDefaulted_GetRef();
		Map->Name = TEXT("MaxDistance");
		Map->CurrentTarget = (uint8)EWeightMapTargetCommon::MaxDistance;
	}
	Map->bEnabled = true;
	Map->Values.SetNumZeroed(V.Num());
	// Painted mask (vertex colour R, Scripts/split_grandma_cloth_blender.py) when present: it keeps the seams pinned
	// on every side. Otherwise ramp by height.
	const TArray<FColor>& Colors = Lod.PhysicalMeshData.VertexColors;
	bool bPainted = false;
	for (int32 i = 0; i < Colors.Num() && !bPainted; ++i) bPainted = Colors[i].R > 0;
	for (int32 i = 0; i < V.Num(); ++i)
	{
		if (bPainted && Colors.IsValidIndex(i))
		{
			Map->Values[i] = MaxDistanceCm * (Colors[i].R / 255.f);
			continue;
		}
		const float T = FMath::Clamp((PinZ - V[i].Z) / FMath::Max(PinZ - ZMin, 1.f), 0.f, 1.f);
		Map->Values[i] = MaxDistanceCm * FMath::SmoothStep(0.f, 1.f, T);
	}
	Cloth->ApplyParameterMasks();

	// World gravity is 0 in this project; give the cloth its own.
	TArray<UObject*> Inner;
	GetObjectsWithOuter(Cloth, Inner, EGetObjectsFlags::None);
	for (UObject* O : Inner)
	{
		if (UChaosClothConfig* Cfg = Cast<UChaosClothConfig>(O))
		{
			Cfg->bUseGravityOverride = true;
			Cfg->Gravity = FVector(0.0, 0.0, -980.665);
		}
	}

	Mesh->AddClothingAsset(Cloth);
	if (!Cloth->BindToSkeletalMesh(Mesh, LodIndex, SectionIndex, 0))
	{
		UE_LOG(LogStreetballEditor, Error, TEXT("CreateClothFromSection: bind failed"));
		return nullptr;
	}
	Mesh->MarkPackageDirty();
	UE_LOG(LogStreetballEditor, Log, TEXT("Cloth %s: %d particles, z %.1f..%.1f cm, mask %s, max %.1f cm"),
		*AssetName, V.Num(), ZMin, ZMax, bPainted ? TEXT("vertex colour R") : TEXT("height"), MaxDistanceCm);
	return Cloth;
}

TArray<FString> UStreetballEditorLibrary::GetMaterialCompileErrors(UMaterialInterface* Material)
{
	TArray<FString> Out;
	UMaterial* M = Material ? Material->GetMaterial() : nullptr;
	if (!M) { Out.Add(TEXT("no material")); return Out; }
	const EShaderPlatform Platform = GMaxRHIShaderPlatform;
	M->ForceRecompileForRendering();
	if (GShaderCompilingManager) GShaderCompilingManager->FinishAllCompilation();
	if (FMaterialResource* R = M->GetMaterialResource(Platform))
	{
		R->FinishCompilation();
		Out = R->GetCompileErrors();
	}
	else
	{
		Out.Add(TEXT("no material resource for the shader platform"));
	}
	return Out;
}
