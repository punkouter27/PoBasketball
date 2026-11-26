#pragma once

#include "CoreMinimal.h"
#include "Kismet/BlueprintFunctionLibrary.h"
#include "StreetballEditorLibrary.generated.h"

class USkeletalMesh;
class UNiagaraSystem;
class UMaterialInterface;
class UTexture2D;
class USoundWave;

/**
 * Headless asset-authoring helpers for Python (unreal.StreetballEditorLibrary). Generic reflection access lets the
 * build scripts tune Niagara lightweight-emitter modules and cloth configs whose classes Python does not expose.
 * Cosmetic assets only: nothing here touches the MuJoCo sim, the policies or the shared contracts.
 */
UCLASS()
class UStreetballEditorLibrary : public UBlueprintFunctionLibrary
{
	GENERATED_BODY()
public:
	/** "Name = <export text>" for every property of Obj (one per line). */
	UFUNCTION(BlueprintCallable, Category = "Streetball|Editor")
	static FString DescribeObject(UObject* Obj);

	/** Objects whose direct outer is Outer (e.g. a Niagara system's emitters, an emitter's modules). */
	UFUNCTION(BlueprintCallable, Category = "Streetball|Editor")
	static TArray<UObject*> GetInnerObjects(UObject* Outer);

	/**
	 * Set a property from export text. Path is dot separated through struct members, e.g. "SpawnInfos" or
	 * "LifetimeDistribution.Min"; the last element gets ImportText. Calls Pre/PostEditChange so derived data rebuilds.
	 */
	UFUNCTION(BlueprintCallable, Category = "Streetball|Editor")
	static bool SetPropertyText(UObject* Obj, const FString& Path, const FString& Value);

	UFUNCTION(BlueprintCallable, Category = "Streetball|Editor")
	static FString GetPropertyText(UObject* Obj, const FString& Path);

	/** Enable or disable one emitter handle of a system by its name. */
	UFUNCTION(BlueprintCallable, Category = "Streetball|Editor")
	static bool SetNiagaraEmitterEnabled(UNiagaraSystem* System, const FString& EmitterName, bool bEnabled);

	/** Emitter handle names of a system. */
	UFUNCTION(BlueprintCallable, Category = "Streetball|Editor")
	static TArray<FString> GetNiagaraEmitterNames(UNiagaraSystem* System);

	/** Recompile a system after edits and wait for it. */
	UFUNCTION(BlueprintCallable, Category = "Streetball|Editor")
	static bool CompileNiagaraSystem(UNiagaraSystem* System);

	/** Compile a material for the running shader platform and return its compile errors (empty = compiles). */
	UFUNCTION(BlueprintCallable, Category = "Streetball|Editor")
	static TArray<FString> GetMaterialCompileErrors(UMaterialInterface* Material);

	/**
	 * Turn one render section of a skeletal mesh into Chaos cloth. Max Distance is painted from height: the top
	 * PinFraction of the section stays skinned (0 cm), below it the allowed travel ramps to MaxDistanceCm at the hem.
	 * Gravity is overridden on the cloth config because the project's world gravity is 0 (MuJoCo owns gravity).
	 */
	UFUNCTION(BlueprintCallable, Category = "Streetball|Editor")
	static UObject* CreateClothFromSection(USkeletalMesh* Mesh, int32 LodIndex, int32 SectionIndex, float MaxDistanceCm, float PinFraction, const FString& AssetName);

	/** Apply standardized BC7/BC5 compression and max-size preset to an imported texture. */
	UFUNCTION(BlueprintCallable, Category = "Streetball|Editor")
	static bool ApplyTextureImportPreset(UTexture2D* Texture, bool bNormalMap, int32 MaxTextureSize = 2048);

	/** Apply standardized 48 kHz streaming/compression preset to an imported sound wave. */
	UFUNCTION(BlueprintCallable, Category = "Streetball|Editor")
	static bool ApplyAudioImportPreset(USoundWave* Wave, int32 CompressionQuality = 75);
};
