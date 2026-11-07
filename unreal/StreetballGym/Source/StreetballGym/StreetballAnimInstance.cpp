#include "StreetballAnimInstance.h"
#include "BoneContainer.h"
#include "BonePose.h"

void FStreetballAnimProxy::PreUpdate(UAnimInstance* InAnimInstance, float DeltaSeconds)
{
	FAnimInstanceProxy::PreUpdate(InAnimInstance, DeltaSeconds);
	if (const UStreetballAnimInstance* Inst = Cast<UStreetballAnimInstance>(InAnimInstance))
	{
		Targets = Inst->GetPendingTargets();
	}
}

bool FStreetballAnimProxy::Evaluate(FPoseContext& Output)
{
	Output.ResetToRefPose();
	if (!Targets.bValid)
	{
		return true;
	}

	const FBoneContainer& BC = Output.Pose.GetBoneContainer();
	const int32 NumBones = Output.Pose.GetNumBones();

	// Resolve mesh-bone-indexed targets to compact pose indices for this LOD.
	TMap<int32, FQuat> RotByCompact;
	TMap<int32, FVector> PosByCompact;
	for (const TPair<int32, FQuat>& P : Targets.Rotations)
	{
		const FCompactPoseBoneIndex C = BC.MakeCompactPoseIndex(FMeshPoseBoneIndex(P.Key));
		if (C != INDEX_NONE) RotByCompact.Add(C.GetInt(), P.Value);
	}
	for (const TPair<int32, FVector>& P : Targets.Positions)
	{
		const FCompactPoseBoneIndex C = BC.MakeCompactPoseIndex(FMeshPoseBoneIndex(P.Key));
		if (C != INDEX_NONE) PosByCompact.Add(C.GetInt(), P.Value);
	}

	// Walk parents-before-children (compact pose order guarantees it), building component-space
	// transforms, overriding rotation (and position for the pelvis) where driven, and writing the
	// resulting local transforms back into the pose.
	TArray<FTransform> CS;
	CS.SetNum(NumBones);
	for (int32 i = 0; i < NumBones; ++i)
	{
		const FCompactPoseBoneIndex Idx(i);
		const FCompactPoseBoneIndex Parent = Output.Pose.GetParentBoneIndex(Idx);
		const FTransform Local = Output.Pose[Idx];
		FTransform Comp = (Parent != INDEX_NONE) ? Local * CS[Parent.GetInt()] : Local;
		if (const FQuat* R = RotByCompact.Find(i)) Comp.SetRotation(*R);
		if (const FVector* T = PosByCompact.Find(i)) Comp.SetTranslation(*T);
		CS[i] = Comp;
		Output.Pose[Idx] = (Parent != INDEX_NONE) ? Comp.GetRelativeTransform(CS[Parent.GetInt()]) : Comp;
	}
	return true;
}
