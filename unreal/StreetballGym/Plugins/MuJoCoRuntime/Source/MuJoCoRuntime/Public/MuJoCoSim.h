#pragma once

#include "CoreMinimal.h"
#include "UObject/Object.h"
#include <mujoco/mujoco.h>
#include "MuJoCoSim.generated.h"

MUJOCORUNTIME_API DECLARE_LOG_CATEGORY_EXTERN(LogMuJoCo, Log, All);

/** One active contact, in sim units (metres, MuJoCo frame) plus a UE-space copy. */
USTRUCT(BlueprintType)
struct MUJOCORUNTIME_API FMjContact
{
	GENERATED_BODY()

	UPROPERTY(BlueprintReadOnly, Category = "MuJoCo") int32 Geom1 = -1;
	UPROPERTY(BlueprintReadOnly, Category = "MuJoCo") int32 Geom2 = -1;
	UPROPERTY(BlueprintReadOnly, Category = "MuJoCo") FString Geom1Name;
	UPROPERTY(BlueprintReadOnly, Category = "MuJoCo") FString Geom2Name;
	/** Contact position in UE world space (cm). */
	UPROPERTY(BlueprintReadOnly, Category = "MuJoCo") FVector PositionUE = FVector::ZeroVector;
	/** Normal force (N) in the contact frame. */
	UPROPERTY(BlueprintReadOnly, Category = "MuJoCo") float NormalForce = 0.f;
	/** Penetration distance (m, negative when penetrating). */
	UPROPERTY(BlueprintReadOnly, Category = "MuJoCo") float Distance = 0.f;
};

/**
 * Thin owner of one mjModel/mjData pair. All gameplay physics runs here; Chaos is bypassed.
 *
 * Frame conversion (blueprint B.1):
 *   pos_ue  = ( x*100, -y*100, z*100 )
 *   quat_ue = FQuat( X=-qx, Y=qy, Z=-qz, W=qw )   with MuJoCo quaternions stored (w,x,y,z)
 */
UCLASS(BlueprintType)
class MUJOCORUNTIME_API UMuJoCoSim : public UObject
{
	GENERATED_BODY()

public:
	virtual void BeginDestroy() override;

	// ---- lifecycle ---------------------------------------------------------
	UFUNCTION(BlueprintCallable, Category = "MuJoCo")
	bool LoadXml(const FString& Path);

	UFUNCTION(BlueprintCallable, Category = "MuJoCo")
	void Unload();

	UFUNCTION(BlueprintPure, Category = "MuJoCo")
	bool IsLoaded() const { return Model != nullptr && Data != nullptr; }

	// ---- stepping ----------------------------------------------------------
	UFUNCTION(BlueprintCallable, Category = "MuJoCo")
	void Step(int32 NumSteps = 1);

	UFUNCTION(BlueprintCallable, Category = "MuJoCo")
	void Forward();

	UFUNCTION(BlueprintCallable, Category = "MuJoCo")
	bool ResetToKeyframe(const FString& KeyName);

	UFUNCTION(BlueprintCallable, Category = "MuJoCo")
	void ResetData();

	UFUNCTION(BlueprintPure, Category = "MuJoCo")
	float GetTimestep() const { return Model ? (float)Model->opt.timestep : 0.f; }

	UFUNCTION(BlueprintPure, Category = "MuJoCo")
	float GetSimTime() const { return Data ? (float)Data->time : 0.f; }

	// ---- ids ---------------------------------------------------------------
	UFUNCTION(BlueprintPure, Category = "MuJoCo") int32 BodyId(const FString& Name) const;
	UFUNCTION(BlueprintPure, Category = "MuJoCo") int32 JointId(const FString& Name) const;
	UFUNCTION(BlueprintPure, Category = "MuJoCo") int32 ActuatorId(const FString& Name) const;
	UFUNCTION(BlueprintPure, Category = "MuJoCo") int32 SiteId(const FString& Name) const;
	UFUNCTION(BlueprintPure, Category = "MuJoCo") int32 GeomId(const FString& Name) const;
	UFUNCTION(BlueprintPure, Category = "MuJoCo") int32 SensorId(const FString& Name) const;
	UFUNCTION(BlueprintPure, Category = "MuJoCo") int32 KeyId(const FString& Name) const;

	UFUNCTION(BlueprintPure, Category = "MuJoCo") FString BodyName(int32 Id) const;
	UFUNCTION(BlueprintPure, Category = "MuJoCo") FString GeomName(int32 Id) const;
	UFUNCTION(BlueprintPure, Category = "MuJoCo") FString JointName(int32 Id) const;

	UFUNCTION(BlueprintPure, Category = "MuJoCo") int32 NumBodies() const { return Model ? Model->nbody : 0; }
	UFUNCTION(BlueprintPure, Category = "MuJoCo") int32 NumGeoms() const { return Model ? Model->ngeom : 0; }
	UFUNCTION(BlueprintPure, Category = "MuJoCo") int32 NumActuators() const { return Model ? Model->nu : 0; }
	UFUNCTION(BlueprintPure, Category = "MuJoCo") int32 NumQ() const { return Model ? Model->nq : 0; }
	UFUNCTION(BlueprintPure, Category = "MuJoCo") int32 NumV() const { return Model ? Model->nv : 0; }

	// ---- reads (UE space) --------------------------------------------------
	/** World transform (cm, UE frame) of a body. */
	UFUNCTION(BlueprintPure, Category = "MuJoCo")
	FTransform GetBodyTransformUE(int32 BodyId) const;

	UFUNCTION(BlueprintPure, Category = "MuJoCo")
	FVector GetSitePositionUE(int32 SiteId) const;

	/** Geom world transform in UE space, plus its MuJoCo type and half-sizes (m). */
	UFUNCTION(BlueprintPure, Category = "MuJoCo")
	FTransform GetGeomTransformUE(int32 GeomId) const;
	UFUNCTION(BlueprintPure, Category = "MuJoCo") int32 GetGeomType(int32 GeomId) const;
	UFUNCTION(BlueprintPure, Category = "MuJoCo") FVector GetGeomSize(int32 GeomId) const;
	UFUNCTION(BlueprintPure, Category = "MuJoCo") int32 GetGeomBody(int32 GeomId) const;
	UFUNCTION(BlueprintPure, Category = "MuJoCo") FLinearColor GetGeomColor(int32 GeomId) const;
	/** True when the geom belongs to a body with at least one degree of freedom (its pose can change). */
	UFUNCTION(BlueprintPure, Category = "MuJoCo") bool IsBodyDynamic(int32 BodyId) const;

	// ---- reads (sim space, doubles) ----------------------------------------
	void GetBodyPosQuatSim(int32 BodyId, FVector3d& OutPos, FQuat4d& OutQuatWxyz) const;
	/** World-frame linear velocity of a body's frame origin (m/s), from cvel (no mj_objectVelocity export in the 4.0 import lib). */
	FVector3d GetBodyLinearVelocitySim(int32 BodyId) const;
	TConstArrayView<double> QPos() const;
	TConstArrayView<double> QVel() const;
	TConstArrayView<double> SensorData() const;
	double GetSensorValue(int32 SensorId, int32 Component) const;

	// ---- writes ------------------------------------------------------------
	void SetCtrl(TConstArrayView<float> Ctrl);
	void SetCtrlDouble(TConstArrayView<double> Ctrl);
	void SetQPos(TConstArrayView<double> InQPos);
	void SetQVel(TConstArrayView<double> InQVel);

	// ---- contacts ----------------------------------------------------------
	UFUNCTION(BlueprintCallable, Category = "MuJoCo")
	void GetContacts(TArray<FMjContact>& Out) const;
	UFUNCTION(BlueprintPure, Category = "MuJoCo")
	int32 NumContacts() const { return Data ? Data->ncon : 0; }

	// ---- misc --------------------------------------------------------------
	/** Order-sensitive 64-bit hash of qpos (for the fixed-step determinism test). */
	uint64 HashQPos() const;

	mjModel* GetModel() const { return Model; }
	mjData* GetData() const { return Data; }

	// ---- static frame helpers (blueprint B.1) -------------------------------
	static FVector SimToUEPos(const double* P) { return FVector(P[0] * 100.0, -P[1] * 100.0, P[2] * 100.0); }
	static FVector SimToUEVec(const double* V) { return FVector(V[0], -V[1], V[2]); }
	static FQuat SimToUEQuat(const double* Q) { return FQuat(-Q[1], Q[2], -Q[3], Q[0]); } // (w,x,y,z) -> FQuat(X,Y,Z,W)
	static FVector UEToSimPos(const FVector& P) { return FVector(P.X / 100.0, -P.Y / 100.0, P.Z / 100.0); }

private:
	mjModel* Model = nullptr;
	mjData* Data = nullptr;
};
