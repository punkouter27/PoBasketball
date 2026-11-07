#include "MuJoCoBoneMapper.h"
#include "MuJoCoSim.h"
#include "StreetballGym.h"
#include "Components/SkeletalMeshComponent.h"
#include "Engine/SkeletalMesh.h"
#include "Misc/FileHelper.h"
#include "Dom/JsonObject.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"

void UMuJoCoBoneMapper::BindPoseComponentSpace(const USkeletalMeshComponent* InMesh, TArray<FTransform>& Out)
{
	Out.Reset();
	if (!InMesh || !InMesh->GetSkeletalMeshAsset()) return;
	const FReferenceSkeleton& Ref = InMesh->GetSkeletalMeshAsset()->GetRefSkeleton();
	const TArray<FTransform>& Local = Ref.GetRefBonePose();
	Out.SetNum(Local.Num());
	for (int32 i = 0; i < Local.Num(); ++i)
	{
		const int32 P = Ref.GetParentIndex(i);
		Out[i] = (P != INDEX_NONE) ? Local[i] * Out[P] : Local[i];
	}
}

bool UMuJoCoBoneMapper::Initialize(USkeletalMeshComponent* InMesh, UMuJoCoSim* InSim, const FString& SpecPath)
{
	Mesh = InMesh;
	Sim = InSim;
	Driven.Reset();
	if (!Mesh || !Mesh->GetSkeletalMeshAsset() || !Sim || !Sim->IsLoaded())
	{
		UE_LOG(LogStreetball, Error, TEXT("BoneMapper: mesh or sim missing"));
		return false;
	}

	FString Json;
	if (!FFileHelper::LoadFileToString(Json, *SpecPath))
	{
		UE_LOG(LogStreetball, Error, TEXT("BoneMapper: cannot read %s"), *SpecPath);
		return false;
	}
	TSharedPtr<FJsonObject> Root;
	if (!FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Json), Root) || !Root.IsValid())
	{
		UE_LOG(LogStreetball, Error, TEXT("BoneMapper: bad JSON in %s"), *SpecPath);
		return false;
	}
	const TSharedPtr<FJsonObject> Map = Root->GetObjectField(TEXT("body_bone_map"));
	if (!Map.IsValid()) return false;

	const FReferenceSkeleton& Ref = Mesh->GetSkeletalMeshAsset()->GetRefSkeleton();
	PelvisBody = Sim->BodyId(TEXT("pelvis"));
	TorsoBody = Sim->BodyId(TEXT("torso"));

	for (const TPair<FString, TSharedPtr<FJsonValue>>& Entry : Map->Values)
	{
		const FString BodyName = Entry.Key;
		const TSharedPtr<FJsonObject> Obj = Entry.Value->AsObject();
		if (!Obj.IsValid()) continue;
		const int32 BodyId = Sim->BodyId(BodyName);
		if (BodyId < 0)
		{
			UE_LOG(LogStreetball, Warning, TEXT("BoneMapper: body '%s' not in model"), *BodyName);
			continue;
		}
		const TArray<TSharedPtr<FJsonValue>>& Bones = Obj->GetArrayField(TEXT("bones"));
		if (BodyName == TEXT("torso"))
		{
			// spine_01..03 take slerp(I, q_rel, k/3) of the lumbar rotation (blueprint B.3)
			for (int32 k = 0; k < Bones.Num(); ++k)
			{
				FDrivenBone D;
				D.BoneName = FName(*Bones[k]->AsString());
				D.BoneIndex = Ref.FindBoneIndex(D.BoneName);
				D.BodyId = BodyId;
				D.ParentBodyId = PelvisBody;
				D.Fraction = double(k + 1) / double(Bones.Num());
				if (D.BoneIndex != INDEX_NONE) Driven.Add(D);
			}
		}
		else if (BodyName == TEXT("head"))
		{
			continue;   // fixed to torso in sim: neck/head keep ref-local and ride on spine_05
		}
		else
		{
			FDrivenBone D;
			D.BoneName = FName(*Bones[0]->AsString());
			D.BoneIndex = Ref.FindBoneIndex(D.BoneName);
			D.BodyId = BodyId;
			D.bDrivePosition = (BodyName == TEXT("pelvis"));
			if (D.BoneIndex != INDEX_NONE) Driven.Add(D);
		}
	}

	// ---- capture offsets at the reference pose (qpos = 0) --------------------
	TArray<double> SavedQ(Sim->QPos()), SavedV(Sim->QVel());
	Sim->ResetData();
	TArray<FQuat> RefRot;
	RefRot.SetNum(Sim->NumBodies());
	for (int32 b = 0; b < RefRot.Num(); ++b) RefRot[b] = Sim->GetBodyTransformUE(b).GetRotation();

	TArray<FTransform> BindCS;
	BindPoseComponentSpace(Mesh, BindCS);
	const FQuat CompRot = Mesh->GetComponentTransform().GetRotation();
	for (FDrivenBone& D : Driven)
	{
		const FQuat QRef = DrivenRotation(D, RefRot);                       // before offset
		const FQuat BindWorld = CompRot * BindCS[D.BoneIndex].GetRotation();
		D.Offset = QRef.Inverse() * BindWorld;
	}
	Sim->SetQPos(SavedQ);
	Sim->SetQVel(SavedV);
	Sim->Forward();

	UE_LOG(LogStreetball, Log, TEXT("BoneMapper: %d driven bones"), Driven.Num());
	return Driven.Num() > 0;
}

FQuat UMuJoCoBoneMapper::DrivenRotation(const FDrivenBone& D, TConstArrayView<FQuat> BodyRotUE) const
{
	if (D.ParentBodyId != INDEX_NONE)
	{
		const FQuat& QP = BodyRotUE[D.ParentBodyId];
		const FQuat QRel = QP.Inverse() * BodyRotUE[D.BodyId];
		return QP * FQuat::Slerp(FQuat::Identity, QRel, (float)D.Fraction);
	}
	return BodyRotUE[D.BodyId];
}

bool UMuJoCoBoneMapper::ComputeBoneWorldRotation(FName Bone, TConstArrayView<FQuat> BodyRotUE, FQuat& Out) const
{
	for (const FDrivenBone& D : Driven)
	{
		if (D.BoneName == Bone)
		{
			Out = DrivenRotation(D, BodyRotUE) * D.Offset;
			return true;
		}
	}
	return false;
}

void UMuJoCoBoneMapper::Apply(TConstArrayView<FVector> BodyPosUE, TConstArrayView<FQuat> BodyRotUE)
{
	if (!Mesh) return;
	UStreetballAnimInstance* Anim = Cast<UStreetballAnimInstance>(Mesh->GetAnimInstance());
	if (!Anim) return;

	const FTransform CompXf = Mesh->GetComponentTransform();
	const FQuat CompRotInv = CompXf.GetRotation().Inverse();

	FStreetballBoneTargets T;
	T.bValid = true;
	for (const FDrivenBone& D : Driven)
	{
		const FQuat World = DrivenRotation(D, BodyRotUE) * D.Offset;
		T.Rotations.Add(D.BoneIndex, CompRotInv * World);
		if (D.bDrivePosition)
		{
			T.Positions.Add(D.BoneIndex, CompXf.InverseTransformPosition(BodyPosUE[D.BodyId]));
		}
	}
	Anim->SetBoneTargets(T);
}

void UMuJoCoBoneMapper::ApplyFromSim()
{
	if (!Sim || !Sim->IsLoaded()) return;
	const int32 N = Sim->NumBodies();
	TArray<FVector> P; P.SetNum(N);
	TArray<FQuat> R; R.SetNum(N);
	for (int32 b = 0; b < N; ++b)
	{
		const FTransform X = Sim->GetBodyTransformUE(b);
		P[b] = X.GetLocation();
		R[b] = X.GetRotation();
	}
	Apply(P, R);
}
