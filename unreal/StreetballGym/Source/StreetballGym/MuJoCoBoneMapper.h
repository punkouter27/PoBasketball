#pragma once

#include "CoreMinimal.h"
#include "UObject/Object.h"
#include "StreetballAnimInstance.h"
#include "MuJoCoBoneMapper.generated.h"

class UMuJoCoSim;
class USkeletalMeshComponent;

/** One driven mannequin bone (blueprint B.3). */
struct FDrivenBone
{
	FName BoneName;
	int32 BoneIndex = INDEX_NONE;     // mesh bone index
	int32 BodyId = INDEX_NONE;        // sim body whose orientation drives it
	int32 ParentBodyId = INDEX_NONE;  // for spine slerp: pelvis body; INDEX_NONE otherwise
	double Fraction = 1.0;            // slerp fraction for spine_01..03 (1/3, 2/3, 1)
	bool bDrivePosition = false;      // pelvis only
	FQuat Offset = FQuat::Identity;   // inverse(toUE(q_ref_sim)) * q_bind_world
};

/**
 * Blueprint B.1/B.2/B.3: drives mannequin bones in world space from sim body orientations.
 *
 *   offset[b] = inverse( toUE(q_ref_sim[b]) ) * q_bind_world[b]       (captured once at qpos = 0)
 *   q_bone[b] = toUE( q_sim[b] ) * offset[b]                           (every frame)
 *
 * Mirrors sim/tools/check_axes.py. The mesh actor must never be rotated after Initialize; it may
 * be translated freely (the mapper works in the component's world frame each frame).
 */
UCLASS()
class STREETBALLGYM_API UMuJoCoBoneMapper : public UObject
{
	GENERATED_BODY()

public:
	/** Parses body_bone_map from humanoid_spec.json and captures offsets. Temporarily resets the sim to qpos=0. */
	bool Initialize(USkeletalMeshComponent* InMesh, UMuJoCoSim* InSim, const FString& HumanoidSpecJsonPath);

	/**
	 * Compute component-space targets from per-body UE-space world rotations/positions
	 * (typically the clock's interpolated snapshot) and push them to the anim instance.
	 */
	void Apply(TConstArrayView<FVector> BodyPosUE, TConstArrayView<FQuat> BodyRotUE);

	/** Convenience: read the sim's current (non-interpolated) state and Apply. */
	void ApplyFromSim();

	/** Driven world rotation for a bone (what Apply would set), for tests. */
	bool ComputeBoneWorldRotation(FName Bone, TConstArrayView<FQuat> BodyRotUE, FQuat& Out) const;

	const TArray<FDrivenBone>& GetDrivenBones() const { return Driven; }
	int32 GetPelvisBodyId() const { return PelvisBody; }

	/** Bind-pose component-space transforms of the mesh (parents accumulated). */
	static void BindPoseComponentSpace(const USkeletalMeshComponent* Mesh, TArray<FTransform>& Out);

private:
	FQuat DrivenRotation(const FDrivenBone& D, TConstArrayView<FQuat> BodyRotUE) const;

	UPROPERTY() TObjectPtr<USkeletalMeshComponent> Mesh = nullptr;
	UPROPERTY() TObjectPtr<UMuJoCoSim> Sim = nullptr;
	TArray<FDrivenBone> Driven;
	int32 PelvisBody = INDEX_NONE;
	int32 TorsoBody = INDEX_NONE;
};
