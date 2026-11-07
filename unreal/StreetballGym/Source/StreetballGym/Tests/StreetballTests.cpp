// Phase B automation tests (B2, B4, B5, B6, B7). Run headless:
//   UnrealEditor-Cmd.exe StreetballGym.uproject -ExecCmds="Automation RunTests Streetball; Quit" -unattended -nullrhi -nosplash -log
#include "Misc/AutomationTest.h"

#if WITH_DEV_AUTOMATION_TESTS

#include "StreetballGym.h"
#include "StreetballWorld.h"
#include "StreetballAnimInstance.h"
#include "MuJoCoSim.h"
#include "SimClock.h"
#include "MuJoCoBoneMapper.h"
#include "ObsBuilder.h"
#include "PolicyRunner.h"
#include "Components/SkeletalMeshComponent.h"
#include "Engine/Engine.h"
#include "Engine/World.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Dom/JsonObject.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"

namespace
{
	constexpr EAutomationTestFlags Flags = EAutomationTestFlags::EditorContext | EAutomationTestFlags::ProductFilter;

	UMuJoCoSim* NewSim(FAutomationTestBase& T)
	{
		UMuJoCoSim* Sim = NewObject<UMuJoCoSim>(GetTransientPackage());
		Sim->AddToRoot();
		if (!T.TestTrue(TEXT("scene.xml loads"), Sim->LoadXml(Streetball::SceneXmlPath())))
		{
			Sim->RemoveFromRoot();
			return nullptr;
		}
		return Sim;
	}

	void FreeSim(UMuJoCoSim* Sim) { if (Sim) { Sim->Unload(); Sim->RemoveFromRoot(); } }

	/** Temporary game world so actors can be spawned without a level. */
	struct FScopedTestWorld
	{
		UWorld* World = nullptr;
		FScopedTestWorld()
		{
			World = UWorld::CreateWorld(EWorldType::Game, false, TEXT("StreetballTestWorld"));
			FWorldContext& Ctx = GEngine->CreateNewWorldContext(EWorldType::Game);
			Ctx.SetCurrentWorld(World);
			World->InitializeActorsForPlay(FURL());
			World->BeginPlay();
		}
		~FScopedTestWorld()
		{
			if (World)
			{
				GEngine->DestroyWorldContext(World);
				World->DestroyWorld(false);
			}
		}
	};

	bool LoadJson(const FString& Path, TSharedPtr<FJsonObject>& Out)
	{
		FString S;
		if (!FFileHelper::LoadFileToString(S, *Path)) return false;
		return FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(S), Out) && Out.IsValid();
	}

	void JsonArrayToDoubles(const TArray<TSharedPtr<FJsonValue>>& A, TArray<double>& Out)
	{
		Out.Reset(A.Num());
		for (const TSharedPtr<FJsonValue>& V : A) Out.Add(V->AsNumber());
	}

	double QuatAngleDeg(const FQuat& A, const FQuat& B)
	{
		const double D = FMath::Abs((double)(A | B));
		return FMath::RadiansToDegrees(2.0 * FMath::Acos(FMath::Min(1.0, D)));
	}
}

// ---------------------------------------------------------------------------- B2: load
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FStreetballSimLoadTest, "Streetball.B2.SimLoad", Flags)
bool FStreetballSimLoadTest::RunTest(const FString&)
{
	UMuJoCoSim* Sim = NewSim(*this);
	if (!Sim) return false;
	TestEqual(TEXT("nq"), Sim->NumQ(), 41);
	TestEqual(TEXT("nv"), Sim->NumV(), 39);
	TestEqual(TEXT("nu"), Sim->NumActuators(), 27);
	TestTrue(TEXT("keyframe stand"), Sim->ResetToKeyframe(TEXT("stand")));
	TestTrue(TEXT("timestep 0.002"), FMath::IsNearlyEqual(Sim->GetTimestep(), 0.002f, 1e-6f));
	// 500 steps and time the raw step cost
	const double T0 = FPlatformTime::Seconds();
	Sim->Step(500);
	const double Ms = (FPlatformTime::Seconds() - T0) * 1000.0 / 500.0;
	AddInfo(FString::Printf(TEXT("mj_step cost: %.4f ms/step (budget < 1 ms)"), Ms));
	TestTrue(TEXT("step under 1 ms"), Ms < 1.0);
	TArray<FMjContact> C;
	Sim->GetContacts(C);
	AddInfo(FString::Printf(TEXT("%d contacts after 1 s"), C.Num()));
	FreeSim(Sim);
	return true;
}

// ---------------------------------------------------------------------------- B4: fixed step
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FStreetballClockTest, "Streetball.B4.ClockDeterminism", Flags)
bool FStreetballClockTest::RunTest(const FString&)
{
	const int64 TargetStep = 1500;   // 3 s of sim
	const double FrameRates[] = {10.0, 30.0, 60.0, 144.0};
	TArray<uint64> Hashes;
	for (double Fps : FrameRates)
	{
		UMuJoCoSim* Sim = NewSim(*this);
		if (!Sim) return false;
		Sim->ResetToKeyframe(TEXT("stand"));
		const int32 Key = Sim->KeyId(TEXT("stand"));
		TArray<float> Hold; Hold.SetNum(Sim->NumActuators());
		for (int32 i = 0; i < Hold.Num(); ++i) Hold[i] = (float)Sim->GetModel()->key_ctrl[Key * Sim->NumActuators() + i];

		USimClock* Clock = NewObject<USimClock>(GetTransientPackage());
		Clock->AddToRoot();
		Clock->Initialize(Sim, 10);
		uint64 HashAtTarget = 0;
		Clock->OnControlStep.BindLambda([&](UMuJoCoSim* S)
		{
			S->SetCtrl(Hold);
			if (Clock->GetStepCount() == TargetStep) HashAtTarget = S->HashQPos();
		});
		// Jittered frame times around the nominal rate: a real frame pacer is never exact.
		FRandomStream Rng((int32)Fps);
		while (Clock->GetStepCount() < TargetStep + 10)
		{
			Clock->Advance((1.0 / Fps) * Rng.FRandRange(0.8, 1.2));
		}
		TestTrue(FString::Printf(TEXT("hash captured at %.0f fps"), Fps), HashAtTarget != 0);
		Hashes.Add(HashAtTarget);
		Clock->RemoveFromRoot();
		FreeSim(Sim);
	}
	for (int32 i = 1; i < Hashes.Num(); ++i)
	{
		TestEqual(FString::Printf(TEXT("qpos hash at step %lld identical for %.0f vs %.0f fps"), TargetStep, FrameRates[0], FrameRates[i]), Hashes[i], Hashes[0]);
	}
	AddInfo(FString::Printf(TEXT("qpos hash at step %lld: %016llx"), TargetStep, Hashes.Num() ? Hashes[0] : 0ull));
	return true;
}

// ---------------------------------------------------------------------------- B3 + B5: world, bones
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FStreetballBoneMapperTest, "Streetball.B5.BoneMapper", Flags)
bool FStreetballBoneMapperTest::RunTest(const FString&)
{
	FScopedTestWorld TW;
	AStreetballWorld* W = TW.World->SpawnActor<AStreetballWorld>();
	if (!TestNotNull(TEXT("world actor"), W)) return false;
	// A bare UWorld has no game mode, so actor BeginPlay never runs: build the world explicitly.
	if (!W->GetSim()) { TestTrue(TEXT("Setup"), W->Setup(TW.World)); }
	UMuJoCoSim* Sim = W->GetSim();
	UMuJoCoBoneMapper* Mapper = W->GetBoneMapper();
	AStreetballCharacter* Ch = W->GetCharacter();
	if (!TestNotNull(TEXT("sim"), Sim) || !TestNotNull(TEXT("mapper"), Mapper) || !TestNotNull(TEXT("character"), Ch)) return false;
	TestTrue(TEXT("mannequin mesh loaded"), Ch->Mesh->GetSkeletalMeshAsset() != nullptr);
	TestEqual(TEXT("driven bones (pelvis + 3 spine + 12 limb)"), Mapper->GetDrivenBones().Num(), 16);
	TestFalse(TEXT("Chaos off on character"), Ch->Mesh->IsSimulatingPhysics());
	TestEqual(TEXT("character collision disabled"), (int32)Ch->Mesh->GetCollisionEnabled(), (int32)ECollisionEnabled::NoCollision);

	const FQuat CompRot = Ch->Mesh->GetComponentTransform().GetRotation();
	TArray<FTransform> BindCS;
	UMuJoCoBoneMapper::BindPoseComponentSpace(Ch->Mesh, BindCS);
	const FReferenceSkeleton& Ref = Ch->Mesh->GetSkeletalMeshAsset()->GetRefSkeleton();

	auto BodyRots = [&](TArray<FQuat>& R, TArray<FVector>& P)
	{
		R.SetNum(Sim->NumBodies()); P.SetNum(Sim->NumBodies());
		for (int32 b = 0; b < R.Num(); ++b) { const FTransform X = Sim->GetBodyTransformUE(b); R[b] = X.GetRotation(); P[b] = X.GetLocation(); }
	};

	// [1] reference pose reproduces the bind pose
	Sim->ResetData();
	TArray<FQuat> R; TArray<FVector> P; BodyRots(R, P);
	double Worst = 0.0;
	for (const FDrivenBone& D : Mapper->GetDrivenBones())
	{
		FQuat Q; Mapper->ComputeBoneWorldRotation(D.BoneName, R, Q);
		Worst = FMath::Max(Worst, QuatAngleDeg(Q, CompRot * BindCS[D.BoneIndex].GetRotation()));
	}
	AddInfo(FString::Printf(TEXT("[1] reference pose max bone error %.5f deg"), Worst));
	TestTrue(TEXT("reference pose error < 0.1 deg"), Worst < 0.1);

	// [2] 90 deg left hip flexion -> thigh points along actor +X (sim forward), horizontal
	auto DirAfter = [&](const TCHAR* Joint, double Deg, const TCHAR* Bone, const TCHAR* Child, FVector& Out)
	{
		Sim->ResetData();
		const int32 J = Sim->JointId(Joint);
		TArray<double> Q(Sim->QPos());
		Q[Sim->GetModel()->jnt_qposadr[J]] = FMath::DegreesToRadians(Deg);
		Sim->SetQPos(Q); Sim->Forward();
		BodyRots(R, P);
		FQuat World; Mapper->ComputeBoneWorldRotation(FName(Bone), R, World);
		const int32 Bi = Ref.FindBoneIndex(FName(Bone)), Ci = Ref.FindBoneIndex(FName(Child));
		const FVector BindDir = BindCS[Ci].GetLocation() - BindCS[Bi].GetLocation();            // component space
		const FVector Local = BindCS[Bi].GetRotation().Inverse().RotateVector(BindDir);
		Out = World.RotateVector(Local).GetSafeNormal();
	};
	FVector V;
	DirAfter(TEXT("hip_flex_l"), 90.0, TEXT("thigh_l"), TEXT("calf_l"), V);
	AddInfo(FString::Printf(TEXT("[2] hip_flex_l=90 -> thigh dir (actor space) = %s, expect ~(+1,0,0)"), *V.ToString()));
	TestTrue(TEXT("thigh forward"), V.X > 0.95 && FMath::Abs(V.Z) < 0.2);
	DirAfter(TEXT("knee_l"), 85.0, TEXT("calf_l"), TEXT("foot_l"), V);   // 90 anatomical minus 5 deg already in A-pose
	AddInfo(FString::Printf(TEXT("[2] knee_l=90 anat -> calf dir = %s, expect ~(-1,0,0)"), *V.ToString()));
	TestTrue(TEXT("heel kicks back"), V.X < -0.9);
	DirAfter(TEXT("shoulder_pitch_l"), 90.0, TEXT("upperarm_l"), TEXT("lowerarm_l"), V);
	AddInfo(FString::Printf(TEXT("[2] shoulder_pitch_l=90 -> upper arm dir = %s, expect forward-ish"), *V.ToString()));
	TestTrue(TEXT("arm forward"), V.X > 0.6 && V.Z > -0.4);

	// [3] the anim proxy actually writes the pose: evaluate once and compare the thigh bone
	Sim->ResetData();
	{
		TArray<double> Q(Sim->QPos());
		Q[Sim->GetModel()->jnt_qposadr[Sim->JointId(TEXT("hip_flex_l"))]] = FMath::DegreesToRadians(45.0);
		Sim->SetQPos(Q); Sim->Forward();
	}
	Mapper->ApplyFromSim();
	Ch->Mesh->TickAnimation(0.f, false);
	Ch->Mesh->RefreshBoneTransforms();
	BodyRots(R, P);
	FQuat Expected; Mapper->ComputeBoneWorldRotation(TEXT("thigh_l"), R, Expected);
	const FQuat Actual = Ch->Mesh->GetBoneQuaternion(TEXT("thigh_l"), EBoneSpaces::WorldSpace);
	const double PoseErr = QuatAngleDeg(Expected, Actual);
	AddInfo(FString::Printf(TEXT("[3] anim proxy thigh_l error vs mapper: %.4f deg"), PoseErr));
	TestTrue(TEXT("anim proxy applies targets (< 0.1 deg)"), PoseErr < 0.1);
	const FVector PelvisBone = Ch->Mesh->GetBoneLocation(TEXT("pelvis"), EBoneSpaces::WorldSpace);
	const FVector PelvisSim = Sim->GetBodyTransformUE(Sim->BodyId(TEXT("pelvis"))).GetLocation();
	AddInfo(FString::Printf(TEXT("[3] pelvis bone %s vs sim %s"), *PelvisBone.ToString(), *PelvisSim.ToString()));
	TestTrue(TEXT("pelvis bone at sim pelvis (< 0.5 cm)"), FVector::Dist(PelvisBone, PelvisSim) < 0.5);
	return true;
}

// ---------------------------------------------------------------------------- B6: replay
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FStreetballReplayTest, "Streetball.B6.Replay", Flags)
bool FStreetballReplayTest::RunTest(const FString&)
{
	const FString Path = FPaths::Combine(Streetball::RepoSharedDir(), TEXT("golden/replay_random.json"));
	TSharedPtr<FJsonObject> J;
	if (!TestTrue(FString::Printf(TEXT("load %s"), *Path), LoadJson(Path, J))) return false;
	UMuJoCoSim* Sim = NewSim(*this);
	if (!Sim) return false;

	const int32 Substeps = (int32)J->GetNumberField(TEXT("substeps"));
	const int32 Steps = (int32)J->GetNumberField(TEXT("steps"));
	TArray<double> Q0, V0; JsonArrayToDoubles(J->GetArrayField(TEXT("qpos0")), Q0); JsonArrayToDoubles(J->GetArrayField(TEXT("qvel0")), V0);
	const TArray<TSharedPtr<FJsonValue>>& Ctrl = J->GetArrayField(TEXT("ctrl"));
	const TArray<TSharedPtr<FJsonValue>>& QPos = J->GetArrayField(TEXT("qpos"));
	TestEqual(TEXT("nq"), (int32)J->GetNumberField(TEXT("nq")), Sim->NumQ());

	Sim->ResetToKeyframe(J->GetStringField(TEXT("key")));
	Sim->SetQPos(Q0); Sim->SetQVel(V0); Sim->Forward();

	const mjModel* M = Sim->GetModel();
	const int32 RootQ = M->jnt_qposadr[Sim->JointId(TEXT("root"))];
	TArray<int32> JAdr;
	for (int32 i = 0; i < M->nu; ++i) JAdr.Add(M->jnt_qposadr[M->actuator_trnid[2 * i]]);

	double MaxRoot = 0.0, MaxJoint = 0.0;
	TArray<double> C, Rec;
	for (int32 t = 0; t < Steps; ++t)
	{
		JsonArrayToDoubles(Ctrl[t]->AsArray(), C);
		Sim->SetCtrlDouble(C);
		Sim->Step(Substeps);
		JsonArrayToDoubles(QPos[t]->AsArray(), Rec);
		const TConstArrayView<double> Q = Sim->QPos();
		const double R = FMath::Sqrt(FMath::Square(Q[RootQ] - Rec[RootQ]) + FMath::Square(Q[RootQ + 1] - Rec[RootQ + 1]) + FMath::Square(Q[RootQ + 2] - Rec[RootQ + 2]));
		MaxRoot = FMath::Max(MaxRoot, R);
		for (int32 a : JAdr) MaxJoint = FMath::Max(MaxJoint, FMath::Abs(Q[a] - Rec[a]));
	}
	AddInfo(FString::Printf(TEXT("replay %d steps x %d: max root error %.4f cm, max joint error %.5f deg"), Steps, Substeps, MaxRoot * 100.0, FMath::RadiansToDegrees(MaxJoint)));
	TestTrue(TEXT("root < 2 cm"), MaxRoot < 0.02);
	TestTrue(TEXT("joints < 1 deg"), FMath::RadiansToDegrees(MaxJoint) < 1.0);
	FreeSim(Sim);
	return true;
}

// ---------------------------------------------------------------------------- B7a: obs golden
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FStreetballObsGoldenTest, "Streetball.B7.ObsGolden", Flags)
bool FStreetballObsGoldenTest::RunTest(const FString&)
{
	const FString Path = FPaths::Combine(Streetball::RepoSharedDir(), TEXT("golden/obs_golden.bin"));
	TArray<uint8> Bytes;
	if (!TestTrue(FString::Printf(TEXT("load %s"), *Path), FFileHelper::LoadFileToArray(Bytes, *Path))) return false;
	const int32* H = reinterpret_cast<const int32*>(Bytes.GetData());
	if (!TestEqual(TEXT("magic"), H[0], 0x0B5601D)) return false;
	const int32 N = H[1], NQ = H[2], NV = H[3], NA = H[4], NT = H[5], NO = H[6];
	const double* D = reinterpret_cast<const double*>(Bytes.GetData() + 7 * sizeof(int32));
	const double* QPos = D; const double* QVel = QPos + N * NQ; const double* Prev = QVel + N * NV;
	const double* Task = Prev + N * NA; const double* InC = Task + N * NT; const double* Cd = InC + N; const double* Obs = Cd + N;

	UMuJoCoSim* Sim = NewSim(*this);
	if (!Sim) return false;
	TestEqual(TEXT("nq"), NQ, Sim->NumQ()); TestEqual(TEXT("nobs"), NO, FObsBuilder::NumObs);
	FObsBuilder B;
	if (!TestTrue(TEXT("obs builder init"), B.Initialize(Sim, Streetball::ObsSpecPath()))) { FreeSim(Sim); return false; }

	double MaxDiff = 0.0; int32 WorstSlot = -1, WorstSample = -1;
	TArray<float> PrevA, TaskA, Out;
	for (int32 i = 0; i < N; ++i)
	{
		Sim->SetQPos(TConstArrayView<double>(QPos + i * NQ, NQ));
		Sim->SetQVel(TConstArrayView<double>(QVel + i * NV, NV));
		Sim->Forward();
		PrevA.SetNum(NA); for (int32 k = 0; k < NA; ++k) PrevA[k] = (float)Prev[i * NA + k];
		TaskA.SetNum(NT); for (int32 k = 0; k < NT; ++k) TaskA[k] = (float)Task[i * NT + k];
		B.Compute(Sim, PrevA, TaskA, (float)InC[i], (float)Cd[i], Out);
		for (int32 k = 0; k < NO; ++k)
		{
			const double Diff = FMath::Abs((double)Out[k] - Obs[i * NO + k]);
			if (Diff > MaxDiff) { MaxDiff = Diff; WorstSlot = k; WorstSample = i; }
		}
	}
	AddInfo(FString::Printf(TEXT("obs golden: %d samples, max abs diff %.3e at slot %d (sample %d)"), N, MaxDiff, WorstSlot, WorstSample));
	TestTrue(TEXT("max abs diff < 1e-5"), MaxDiff < 1e-5);
	FreeSim(Sim);
	return true;
}

// ---------------------------------------------------------------------------- B7b: NNE policy
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FStreetballPolicyTest, "Streetball.B7.PolicyRunner", Flags)
bool FStreetballPolicyTest::RunTest(const FString&)
{
	const FString Onnx = FPaths::Combine(Streetball::RepoSharedDir(), TEXT("dummy_policy.onnx"));
	TSharedPtr<FJsonObject> Side;
	if (!TestTrue(TEXT("sidecar json"), LoadJson(FPaths::ChangeExtension(Onnx, TEXT("json")), Side))) return false;
	UPolicyRunner* Runner = NewObject<UPolicyRunner>(GetTransientPackage());
	Runner->AddToRoot();
	if (!TestTrue(TEXT("LoadOnnx"), Runner->LoadOnnx(Onnx, FObsBuilder::NumObs, FObsBuilder::NumAction))) { Runner->RemoveFromRoot(); return false; }

	TArray<double> In, Expect;
	JsonArrayToDoubles(Side->GetArrayField(TEXT("check_input")), In);
	JsonArrayToDoubles(Side->GetArrayField(TEXT("check_output")), Expect);
	TArray<float> Obs; Obs.SetNum(In.Num()); for (int32 i = 0; i < In.Num(); ++i) Obs[i] = (float)In[i];
	TArray<float> Act;
	TestTrue(TEXT("Run"), Runner->Run(Obs, Act));
	double MaxDiff = 0.0;
	for (int32 i = 0; i < Expect.Num() && i < Act.Num(); ++i) MaxDiff = FMath::Max(MaxDiff, FMath::Abs((double)Act[i] - Expect[i]));
	AddInfo(FString::Printf(TEXT("NNE vs onnxruntime(Python) max abs diff %.3e"), MaxDiff));
	TestTrue(TEXT("matches python onnxruntime (< 1e-5)"), MaxDiff < 1e-5);

	double Total = 0.0;
	for (int32 i = 0; i < 200; ++i) { Runner->Run(Obs, Act); Total += Runner->LastInferenceMs; }
	AddInfo(FString::Printf(TEXT("inference: %.3f ms mean over 200 runs (budget 2 ms)"), Total / 200.0));
	TestTrue(TEXT("inference < 2 ms"), Total / 200.0 < 2.0);
	Runner->RemoveFromRoot();
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS
