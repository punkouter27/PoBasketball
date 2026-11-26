// Reward penalty weights and curriculum thresholds, editable in the editor (Po Game Standard C9 / C10).
// Mirrors shared/reward_config.json (what the Python trainer reads); sim/tests/test_unreal_reward_mirror.py fails when the two differ.
// Changing a value here or there does NOT retrain the shipped policies: they keep the weights they were trained with.
#pragma once

#include "CoreMinimal.h"
#include "Engine/DataAsset.h"
#include "StreetballRewardConfig.generated.h"

USTRUCT(BlueprintType)
struct STREETBALLGYM_API FStreetballCurriculumStage
{
	GENERATED_BODY()

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Curriculum") FString Stage;
	/** Gate value that promotes a policy past this stage (unit in Metric). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Curriculum") float Threshold = 0.f;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Curriculum") FString Metric;
};

/** Reward weights (added as weight * term, negative = penalty) and curriculum gates. */
UCLASS(BlueprintType)
class STREETBALLGYM_API UStreetballRewardConfig : public UPrimaryDataAsset
{
	GENERATED_BODY()

public:
	UStreetballRewardConfig();

	/** Joint torque squared: sum of actuator force^2. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Reward|Penalties") float TorqueSqWeight = -1e-05f;
	/** Joint angular velocity squared: sum of joint qvel^2. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Reward|Penalties") float JointAngVelSqWeight = -0.001f;
	/** Action rate: |a_t - a_(t-1)|^2. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Reward|Penalties") float ActionRateSqWeight = -0.05f;
	/** Foot slip: planar foot speed while the foot is in contact. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Reward|Penalties") float FootSlipWeight = -0.1f;
	// 2026-11-24 shaping terms, 0 = off (docs/20261124/log.md); no shipped policy was trained with them.
	/** Mechanical power: mean over actuators of |force * velocity|. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Reward|Penalties") float PowerAbsWeight = 0.0f;
	/** Static stability: |CoM_xy - support centre_xy|^2. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Reward|Penalties") float ComOffsetWeight = -0.2f;
	/** Vertical CoM speed squared. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Reward|Penalties") float ComVelZSqWeight = 0.0f;
	/** Pelvis roll and pitch rate squared. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Reward|Penalties") float AngVelXYSqWeight = -0.02f;
	/** At touchdown: max(0, 0.35 s - swing time), summed over feet. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Reward|Penalties") float ShortSwingWeight = 0.0f;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Curriculum") TArray<FStreetballCurriculumStage> CurriculumStages;

	/** Index of Stage in CurriculumStages, or INDEX_NONE. */
	UFUNCTION(BlueprintPure, Category = "Curriculum") int32 FindStage(const FString& Stage) const;

private:
	void AddStage(const TCHAR* Stage, float Threshold, const TCHAR* Metric);
};
