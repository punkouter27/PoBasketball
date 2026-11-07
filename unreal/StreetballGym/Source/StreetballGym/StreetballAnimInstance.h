#pragma once

#include "CoreMinimal.h"
#include "Animation/AnimInstance.h"
#include "Animation/AnimInstanceProxy.h"
#include "StreetballAnimInstance.generated.h"

/** Component-space bone targets produced by UMuJoCoBoneMapper each frame. */
struct FStreetballBoneTargets
{
	bool bValid = false;
	/** Mesh bone index -> component-space rotation. Only driven bones are present. */
	TMap<int32, FQuat> Rotations;
	/** Mesh bone index -> component-space position (root/pelvis only). */
	TMap<int32, FVector> Positions;
};

struct FStreetballAnimProxy : public FAnimInstanceProxy
{
	FStreetballAnimProxy() = default;
	FStreetballAnimProxy(UAnimInstance* InInstance) : FAnimInstanceProxy(InInstance) {}

	virtual void PreUpdate(UAnimInstance* InAnimInstance, float DeltaSeconds) override;
	virtual bool Evaluate(FPoseContext& Output) override;

	FStreetballBoneTargets Targets;     // worker-thread copy
};

/**
 * Anim instance without an AnimBlueprint: the proxy writes the pose directly from sim-driven
 * component-space targets (blueprint B.2). Bones that are not driven keep their reference local
 * transform and therefore ride rigidly on their parent (spine_04/05, clavicles, neck, head, twist,
 * finger and toe bones).
 */
UCLASS(Transient)
class STREETBALLGYM_API UStreetballAnimInstance : public UAnimInstance
{
	GENERATED_BODY()

public:
	/** Game thread: replace the targets used at the next evaluation. */
	void SetBoneTargets(const FStreetballBoneTargets& InTargets) { PendingTargets = InTargets; }
	const FStreetballBoneTargets& GetPendingTargets() const { return PendingTargets; }

protected:
	virtual FAnimInstanceProxy* CreateAnimInstanceProxy() override { return new FStreetballAnimProxy(this); }
	virtual void DestroyAnimInstanceProxy(FAnimInstanceProxy* InProxy) override { delete InProxy; }

	FStreetballBoneTargets PendingTargets;
};
