// Phase B automation tests for the state machine (C.3), camera (B8), audio (B9) and HUD (B10).
#include "Misc/AutomationTest.h"

#if WITH_DEV_AUTOMATION_TESTS

#include "StreetballGym.h"
#include "StreetballWorld.h"
#include "StreetballDirector.h"
#include "StreetballTracker.h"
#include "StreetballHUDWidget.h"
#include "BroadcastCamera.h"
#include "CourtAudio.h"
#include "MuJoCoSim.h"
#include "PolicyRunner.h"
#include "Blueprint/UserWidget.h"
#include "Engine/Engine.h"
#include "Engine/World.h"

namespace
{
	constexpr EAutomationTestFlags PFlags = EAutomationTestFlags::EditorContext | EAutomationTestFlags::ProductFilter;

	struct FScopedGameWorld
	{
		UWorld* World = nullptr;
		FScopedGameWorld()
		{
			World = UWorld::CreateWorld(EWorldType::Game, false, TEXT("StreetballPresentationTestWorld"));
			FWorldContext& Ctx = GEngine->CreateNewWorldContext(EWorldType::Game);
			Ctx.SetCurrentWorld(World);
			World->InitializeActorsForPlay(FURL());
			World->BeginPlay();
		}
		~FScopedGameWorld()
		{
			if (World) { GEngine->DestroyWorldContext(World); World->DestroyWorld(false); }
		}
	};

	FTrackedState BaseState(double Time)
	{
		FTrackedState S;
		S.Time = Time;
		S.PelvisPos = FVector3d(0, 0, 0.92);
		S.FootPos[0] = FVector2d(0.0, 0.1); S.FootPos[1] = FVector2d(0.0, -0.1);
		S.BallPos = FVector3d(0.45, -0.35, 0.12);
		S.RimPos[0] = FVector3d(12.425, 0, 3.05); S.RimPos[1] = FVector3d(-12.425, 0, 3.05);
		S.InControl = true; S.LooseT = -1.0; S.CountdownFrac = 1.f;
		return S;
	}

	UStreetballDirector* NewDirector()
	{
		UStreetballDirector* D = NewObject<UStreetballDirector>(GetTransientPackage());
		D->AddToRoot();
		D->Initialize(3);
		return D;
	}
}

// ---------------------------------------------------------------------------- state machine
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FStreetballDirectorScrambleTest, "Streetball.C3.Director.ScrambleAndResets", PFlags)
bool FStreetballDirectorScrambleTest::RunTest(const FString&)
{
	UStreetballDirector* D = NewDirector();
	FStreetballDirectorOutput Out;
	FTrackedState S = BaseState(0.0);
	D->ForceState(EStreetballState::DribbleStationary, S);
	D->Update(S, 0.02, Out);
	TestEqual(TEXT("stays in DRIBBLE_STATIONARY with ball in control"), (int32)Out.State, (int32)EStreetballState::DribbleStationary);
	TestEqual(TEXT("policy family dribble"), Out.PolicyName, FString(TEXT("dribble")));
	TestTrue(TEXT("task hand +-1"), FMath::Abs(Out.Task[0]) == 1.f);
	TestEqual(TEXT("task apex target 1.0"), Out.Task[1], 1.f);
	TestTrue(TEXT("stationary dribble: bounces_to_switch in [2,4]"), Out.Task[2] >= 2.f && Out.Task[2] <= 4.f);
	TestTrue(TEXT("stationary dribble: speed/dir/dist zero"), Out.Task[3] == 0.f && Out.Task[4] == 0.f && Out.Task[5] == 0.f && Out.Task[6] == 0.f);

	// ball gets away -> loose -> SCRAMBLE
	S = BaseState(5.02); S.BallPos = FVector3d(4, 0, 0.12); S.InControl = false; S.LooseT = 5.0; S.CountdownFrac = 0.993f;
	D->Update(S, 0.02, Out);
	TestEqual(TEXT("-> SCRAMBLE"), (int32)Out.State, (int32)EStreetballState::Scramble);
	TestEqual(TEXT("scramble policy family"), Out.PolicyName, FString(TEXT("scramble")));
	TestTrue(TEXT("scramble task = countdown"), FMath::IsNearlyEqual(Out.Task[0], 0.993f, 1e-4f));
	TestTrue(TEXT("HUD sees loose"), D->GetProgress().bLoose);
	TestFalse(TEXT("no reset yet"), Out.Reset.bRequested);

	// regain -> back to the previous state
	S = BaseState(6.0); D->Update(S, 0.02, Out);
	TestEqual(TEXT("regain -> DRIBBLE_STATIONARY"), (int32)Out.State, (int32)EStreetballState::DribbleStationary);

	// lose again and let the countdown expire -> HARD_RESET
	S = BaseState(7.02); S.InControl = false; S.LooseT = 7.0; S.CountdownFrac = 0.99f; S.BallPos = FVector3d(5, 0, 0.12);
	D->Update(S, 0.02, Out);
	TestEqual(TEXT("-> SCRAMBLE again"), (int32)Out.State, (int32)EStreetballState::Scramble);
	S = BaseState(10.1); S.InControl = false; S.LooseT = 7.0; S.CountdownFrac = 0.f; S.BallPos = FVector3d(5, 0, 0.12);
	D->Update(S, 0.02, Out);
	TestEqual(TEXT("expiry -> HARD_RESET"), (int32)Out.State, (int32)EStreetballState::HardReset);
	TestTrue(TEXT("reset requested"), Out.Reset.bRequested);
	TestTrue(TEXT("reason mentions countdown"), Out.Reset.Reason.Contains(TEXT("countdown")));
	S = BaseState(10.1);
	D->NotifyResetApplied(S);
	D->Describe(S, Out);
	TestEqual(TEXT("after reset: tier state DRIBBLE_STATIONARY"), (int32)Out.State, (int32)EStreetballState::DribbleStationary);
	TestEqual(TEXT("active tier still 3"), D->GetProgress().ActiveTier, 3);

	// fall -> HARD_RESET ; ball past the fence -> HARD_RESET
	S = BaseState(11.0); S.Fallen = true; D->Update(S, 0.02, Out);
	TestTrue(TEXT("fallen -> reset"), Out.Reset.bRequested && Out.Reset.Reason.Contains(TEXT("fallen")));
	D->NotifyResetApplied(BaseState(11.0));
	S = BaseState(12.0); S.BallOutOfFence = true; D->Update(S, 0.02, Out);
	TestTrue(TEXT("ball past fence -> reset"), Out.Reset.bRequested && Out.Reset.Reason.Contains(TEXT("fence")));
	D->RemoveFromRoot();
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FStreetballDirectorTiersTest, "Streetball.C3.Director.TierProgression", PFlags)
bool FStreetballDirectorTiersTest::RunTest(const FString&)
{
	UStreetballDirector* D = NewDirector();
	FStreetballDirectorOutput Out;
	double T = 0.0;
	const double Dt = 0.02;

	// Tier 1: 60 s balanced, one foot drift resets the timer first
	FTrackedState S = BaseState(T);
	D->Update(S, Dt, Out);
	for (int32 i = 0; i < 500; ++i) { T += Dt; S = BaseState(T); D->Update(S, Dt, Out); }
	TestTrue(TEXT("balance accumulates"), D->GetProgress().BalanceTime > 9.0);
	T += Dt; S = BaseState(T); S.FootPos[0] = FVector2d(0.3, 0.1); D->Update(S, Dt, Out);
	TestTrue(TEXT("stepping out resets the balance timer"), D->GetProgress().BalanceTime < 0.05);
	for (int32 i = 0; i < 3005 && Out.State == EStreetballState::Stand; ++i) { T += Dt; S = BaseState(T); S.FootPos[0] = FVector2d(0.3, 0.1); D->Update(S, Dt, Out); }
	TestTrue(TEXT("tier 1 mastered"), D->GetProgress().Mastered[0]);
	TestEqual(TEXT("-> ROAM"), (int32)Out.State, (int32)EStreetballState::Roam);
	TestEqual(TEXT("roam policy family"), Out.PolicyName, FString(TEXT("locomotion")));

	// Tier 2: walk to 10 waypoints using the task block (heading frame == world frame here)
	int32 Guard = 0;
	while (Out.State == EStreetballState::Roam && Guard++ < 100)
	{
		T += Dt;
		const FVector2d Dir(Out.Task[0], Out.Task[1]);
		const double Dist = Out.Task[2];
		TestTrue(TEXT("speed cmd in range"), Out.Task[3] >= 0.8f && Out.Task[3] <= 3.0f);
		S = BaseState(T);
		S.PelvisPos = FVector3d(S.PelvisPos.X + Dir.X * Dist, S.PelvisPos.Y + Dir.Y * Dist, 0.92);
		// waypoints are absolute: accumulate the pelvis position
		static FVector2d Pos(0, 0);
		if (Guard == 1) Pos = FVector2d(0, 0);
		Pos += Dir * Dist;
		S.PelvisPos = FVector3d(Pos.X, Pos.Y, 0.92);
		D->Update(S, Dt, Out);
	}
	TestTrue(TEXT("tier 2 mastered after 10 waypoints"), D->GetProgress().Mastered[1]);
	TestEqual(TEXT("-> DRIBBLE_STATIONARY"), (int32)Out.State, (int32)EStreetballState::DribbleStationary);
	TestTrue(TEXT("tier 3 start asks for a reset (ball to hand)"), Out.Reset.bRequested);
	D->NotifyResetApplied(BaseState(T));
	D->Describe(BaseState(T), Out);

	// Tier 3: 50 clean bounces (apex in band, active palm touched, ball near), hand switches
	int32 Bounces = 0; Guard = 0;
	while (Out.State == EStreetballState::DribbleStationary && Guard++ < 400)
	{
		const double Hand = Out.Task[0];
		T += Dt; S = BaseState(T); S.BallPos = FVector3d(0.3, -Hand * 0.3, 1.0);      // apex, palm on ball
		S.PalmBall[Hand > 0 ? 1 : 0] = true;
		D->Update(S, Dt, Out);
		if (Out.State != EStreetballState::DribbleStationary) break;
		T += Dt; S = BaseState(T); S.BallPos = FVector3d(0.3, -Hand * 0.3, 0.12); S.BallFloor = true;   // bounce
		D->Update(S, Dt, Out);
		++Bounces;
		if (Out.bBounceEvent && Bounces > 1) TestTrue(TEXT("bounce is clean"), Out.bCleanBounce);
	}
	TestTrue(TEXT("tier 3 mastered"), D->GetProgress().Mastered[2]);
	TestTrue(TEXT("hand switched at least 10 times"), D->GetProgress().HandSwitches >= 10);
	TestEqual(TEXT("-> DRIBBLE_MOVING"), (int32)Out.State, (int32)EStreetballState::DribbleMoving);
	AddInfo(FString::Printf(TEXT("tier 3 took %d bounces, %d hand switches"), Bounces, D->GetProgress().HandSwitches));
	D->RemoveFromRoot();
	return true;
}

// ---------------------------------------------------------------------------- B8 camera
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FStreetballCameraTest, "Streetball.B8.CameraCuts", PFlags)
bool FStreetballCameraTest::RunTest(const FString&)
{
	FBroadcastLogic L;
	FBroadcastInputs In;
	In.Rim[0] = FVector3d(12.425, 0, 3.05); In.Rim[1] = FVector3d(-12.425, 0, 3.05);
	In.Character = FVector3d(0, 0, 0.95); In.Ball = FVector3d(0.5, -0.3, 0.12);
	In.Time = 0.0; In.State = EStreetballState::Stand;
	TestTrue(TEXT("first decision is a cut"), L.Decide(In));
	TestEqual(TEXT("stand at centre -> SIDELINE"), (int32)L.Current, (int32)EBroadcastShot::Sideline);
	FBroadcastTarget T = L.TargetFor(L.Current, In);
	TestTrue(TEXT("sideline dolly sits on the court side (UE y = +930 cm)"), FMath::IsNearlyEqual(T.Position.Y, 930.f, 1.f));
	TestTrue(TEXT("fov within limits"), T.FovDeg >= L.FovMin && T.FovDeg <= L.FovMax);

	In.Time = 0.5; In.State = EStreetballState::JumpShot;
	TestFalse(TEXT("no cut inside 2 s hysteresis"), L.Decide(In));
	In.Time = 2.5;
	TestTrue(TEXT("cut after hysteresis"), L.Decide(In));
	TestEqual(TEXT("JUMP_SHOT -> BASELINE"), (int32)L.Current, (int32)EBroadcastShot::Baseline);
	T = L.TargetFor(L.Current, In);
	TestTrue(TEXT("baseline camera is low"), T.Position.Z < 100.f);

	In.Time = 5.0; In.State = EStreetballState::Roam; In.Speed = 2.6;
	TestTrue(TEXT("sprint -> cut"), L.Decide(In));
	TestEqual(TEXT("ROAM sprint -> PRESS BOX"), (int32)L.Current, (int32)EBroadcastShot::PressBox);
	T = L.TargetFor(L.Current, In);
	TestTrue(TEXT("press box is elevated"), T.Position.Z > 600.f);

	In.Time = 8.0; In.Speed = 1.0;
	TestTrue(TEXT("slow roam -> back to sideline"), L.Decide(In) && L.Current == EBroadcastShot::Sideline);
	In.Time = 11.0; In.State = EStreetballState::Scramble;
	TestTrue(TEXT("SCRAMBLE -> press box"), L.Decide(In) && L.Current == EBroadcastShot::PressBox);
	In.Time = 14.0; In.State = EStreetballState::DribbleMoving; In.Character = FVector3d(8.0, 0, 0.95);
	TestTrue(TEXT("within 6 m of the hoop -> baseline"), L.Decide(In) && L.Current == EBroadcastShot::Baseline);
	L.ForcedShot = 0; In.Time = 17.0;
	TestTrue(TEXT("forced CVar value wins"), L.Decide(In) && L.Current == EBroadcastShot::Sideline);

	// ROAM with the ball parked off court: the sideline shot frames the athlete, not the athlete-ball midpoint
	In.State = EStreetballState::Roam; In.Character = FVector3d(-8.0, -3.0, 0.95); In.Ball = FVector3d(0.0, 8.0, 0.12);
	T = L.TargetFor(EBroadcastShot::Sideline, In);
	TestTrue(TEXT("ROAM: sideline looks at the athlete (UE x = -800 cm)"), FMath::IsNearlyEqual(T.LookAt.X, -800.f, 1.f) && FMath::IsNearlyEqual(T.LookAt.Y, 300.f, 1.f));
	In.State = EStreetballState::DribbleMoving; In.Ball = FVector3d(-7.0, -3.0, 0.5);
	T = L.TargetFor(EBroadcastShot::Sideline, In);
	TestTrue(TEXT("ball in play: sideline frames the athlete-ball midpoint"), FMath::IsNearlyEqual(T.LookAt.X, -750.f, 1.f));

	// smoothing converges without overshoot
	FVector V = FVector::ZeroVector, P = FVector(0, 0, 0);
	const FVector Target(100, 0, 0);
	float MaxX = 0.f;
	for (int32 i = 0; i < 200; ++i) { P = FCriticalDamper::Damp(P, Target, V, 0.4f, 1.f / 60.f); MaxX = FMath::Max(MaxX, (float)P.X); }
	TestTrue(TEXT("critically damped: converges"), FVector::Dist(P, Target) < 1.f);
	TestTrue(TEXT("critically damped: no overshoot"), MaxX <= 100.5f);
	return true;
}

// ---------------------------------------------------------------------------- B9 audio
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FStreetballAudioTest, "Streetball.B9.ContactAudio", PFlags)
bool FStreetballAudioTest::RunTest(const FString&)
{
	UMuJoCoSim* Sim = NewObject<UMuJoCoSim>(GetTransientPackage());
	Sim->AddToRoot();
	if (!TestTrue(TEXT("scene loads"), Sim->LoadXml(Streetball::SceneXmlPath()))) return false;
	Sim->ResetToKeyframe(TEXT("stand"));
	// drop the ball from 1.0 m at (3, 0) away from the character
	TArray<double> Q(Sim->QPos());
	const int32 B = Sim->GetModel()->jnt_qposadr[Sim->JointId(TEXT("ball"))];
	Q[B] = 3.0; Q[B + 1] = 0.0; Q[B + 2] = 1.0 + 0.1205;
	Sim->SetQPos(Q); Sim->Forward();

	FContactAudioProcessor Proc;
	TestTrue(TEXT("processor init"), Proc.Initialize(Sim));
	TArray<FCourtAudioEvent> Events;
	for (int32 i = 0; i < 1500; ++i) { Sim->Step(1); Proc.Process(Sim, Events); }

	TArray<const FCourtAudioEvent*> Floor;
	for (const FCourtAudioEvent& E : Events) if (E.Kind == ECourtSound::BallFloor) Floor.Add(&E);
	TestTrue(TEXT("at least 3 ball-floor bounces heard in 3 s"), Floor.Num() >= 3);
	if (Floor.Num() >= 1)
	{
		AddInfo(FString::Printf(TEXT("first bounce at t=%.3f s, speed %.2f m/s, volume %.2f, pitch %.2f (free fall predicts t=0.452 s, v=4.43 m/s)"),
			Floor[0]->Time, Floor[0]->Speed, Floor[0]->Volume, Floor[0]->Pitch));
		TestTrue(TEXT("first bounce time ~0.45 s"), FMath::Abs(Floor[0]->Time - 0.452) < 0.03);
		TestTrue(TEXT("impact speed ~4.4 m/s"), FMath::Abs(Floor[0]->Speed - 4.43) < 0.5);
		TestTrue(TEXT("volume in (min,1]"), Floor[0]->Volume > Proc.MinVolume && Floor[0]->Volume <= 1.f);
	}
	for (int32 i = 1; i < Floor.Num(); ++i)
	{
		TestTrue(TEXT("bounces debounced >= 60 ms apart"), Floor[i]->Time - Floor[i - 1]->Time >= 0.06);
		if (i == 1) TestTrue(TEXT("second bounce quieter than the first"), Floor[1]->Volume < Floor[0]->Volume);
	}
	int32 NonBall = 0;
	for (const FCourtAudioEvent& E : Events) if (E.Kind != ECourtSound::BallFloor) ++NonBall;
	AddInfo(FString::Printf(TEXT("%d events total (%d ball-floor, %d other)"), Events.Num(), Floor.Num(), NonBall));
	// mapping sanity
	const FCourtAudioEvent Loud = Proc.MakeEvent(ECourtSound::BallRim, 0, FVector3d::ZeroVector, 100.f, TEXT("x"));
	const FCourtAudioEvent Soft = Proc.MakeEvent(ECourtSound::BallRim, 0, FVector3d::ZeroVector, 0.f, TEXT("x"));
	TestEqual(TEXT("full volume at high speed"), Loud.Volume, 1.f);
	TestEqual(TEXT("min volume at zero speed"), Soft.Volume, Proc.MinVolume);
	TestTrue(TEXT("pitch rises with speed"), Loud.Pitch > Soft.Pitch);
	Sim->Unload(); Sim->RemoveFromRoot();
	return true;
}

// ---------------------------------------------------------------------------- B10 HUD
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FStreetballHUDTest, "Streetball.B10.HUD", PFlags)
bool FStreetballHUDTest::RunTest(const FString&)
{
	FScopedGameWorld TW;
	UStreetballHUDWidget* HUD = CreateWidget<UStreetballHUDWidget>(TW.World, UStreetballHUDWidget::StaticClass());
	if (!TestNotNull(TEXT("widget"), HUD)) return false;
	HUD->TakeWidget();   // builds the C++ widget tree
	FStreetballProgress P;
	P.ActiveTier = 4; P.TierName = TEXT("Tier 4: Dynamic Roam & Dribble");
	P.Mastered[0] = P.Mastered[1] = P.Mastered[2] = true;
	P.CleanStreak = 17; P.Saves = 2; P.TotalDistance = 123.4; P.Progress01 = 0.55f; P.bLoose = true; P.CountdownFrac = 0.4f;
	HUD->UpdateFromProgress(P, EStreetballState::Scramble);
	TestEqual(TEXT("tier text"), HUD->GetTierText(), FString(TEXT("Tier 4: Dynamic Roam & Dribble")));
	TestTrue(TEXT("streak shown"), HUD->GetStreakText().Contains(TEXT("Clean dribbles: 17")));
	TestTrue(TEXT("distance shown"), HUD->GetDistanceText().Contains(TEXT("123.4 m")));
	TestTrue(TEXT("milestones: three checks"), HUD->GetMilestoneText().Contains(TEXT("[x] T1  [x] T2  [x] T3  [ ] T4")));
	TestTrue(TEXT("percent"), FMath::IsNearlyEqual(HUD->GetProgressPercent(), 55.f, 0.01f));
	TestTrue(TEXT("countdown ring visible while loose"), HUD->IsCountdownVisible());
	P.bLoose = false; P.CountdownFrac = 1.f;
	HUD->UpdateFromProgress(P, EStreetballState::DribbleMoving);
	TestFalse(TEXT("countdown hidden when in control"), HUD->IsCountdownVisible());

	// UU_AGENT build stamp: "build YYMMDD", six digits, matching the compile date format
	const FString Stamp = UStreetballHUDWidget::BuildStampYYMMDD();
	TestEqual(TEXT("stamp is 6 characters"), Stamp.Len(), 6);
	TestTrue(TEXT("stamp is all digits"), Stamp.IsNumeric() && !Stamp.Contains(TEXT(".")) && !Stamp.Contains(TEXT("-")));
	const int32 MM = FCString::Atoi(*Stamp.Mid(2, 2)), DD = FCString::Atoi(*Stamp.Mid(4, 2));
	TestTrue(TEXT("stamp month/day in range"), MM >= 1 && MM <= 12 && DD >= 1 && DD <= 31);
	const FString Today = FDateTime::Now().ToString(TEXT("%y%m%d"));
	AddInfo(FString::Printf(TEXT("build stamp %s (today %s); HUD text '%s'"), *Stamp, *Today, *HUD->GetBuildStampText()));
	TestTrue(TEXT("HUD shows the stamp bottom-right"), HUD->GetBuildStampText() == FString::Printf(TEXT("build %s"), *Stamp));
	return true;
}

// ---------------------------------------------------------------------------- transition table
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FStreetballTransitionTableTest, "Streetball.C3.TransitionTable", PFlags)
bool FStreetballTransitionTableTest::RunTest(const FString&)
{
	UStreetballDirector* D = NewObject<UStreetballDirector>(GetTransientPackage());
	D->AddToRoot();
	const FString Path = FPaths::Combine(Streetball::RepoSharedDir(), TEXT("transition_table.json"));
	if (!TestTrue(TEXT("load shared/transition_table.json"), D->LoadTransitionTable(Path))) { D->RemoveFromRoot(); return false; }
	D->Initialize(1);
	TestEqual(TEXT("version 1"), D->TableVersion(), 1);
	TestEqual(TEXT("STAND -> balance"), D->PolicyFor(EStreetballState::Stand), FString(TEXT("balance")));
	TestEqual(TEXT("ROAM -> locomotion"), D->PolicyFor(EStreetballState::Roam), FString(TEXT("locomotion")));
	TestEqual(TEXT("DRIBBLE_STATIONARY -> dribble"), D->PolicyFor(EStreetballState::DribbleStationary), FString(TEXT("dribble")));
	TestEqual(TEXT("DRIBBLE_MOVING -> dribble"), D->PolicyFor(EStreetballState::DribbleMoving), FString(TEXT("dribble")));
	TestEqual(TEXT("JUMP_SHOT -> shot"), D->PolicyFor(EStreetballState::JumpShot), FString(TEXT("shot")));
	TestEqual(TEXT("SCRAMBLE -> scramble"), D->PolicyFor(EStreetballState::Scramble), FString(TEXT("scramble")));
	TestEqual(TEXT("balance file"), D->PolicyFileFor(TEXT("balance")), FString(TEXT("policies/balance.onnx")));
	TestEqual(TEXT("dribble layout has 7 fields"), D->LayoutFor(TEXT("dribble")).Num(), 7);
	TestEqual(TEXT("dribble layout[3] = speed_cmd"), D->LayoutFor(TEXT("dribble"))[3], FString(TEXT("speed_cmd")));
	TestEqual(TEXT("shot layout[4] = time_since_trigger_s"), D->LayoutFor(TEXT("shot"))[4], FString(TEXT("time_since_trigger_s")));

	// DRIBBLE_MOVING task: [hand, apex, 0 (no commanded switches), speed in [1.5,2.5], dir, dist]
	FStreetballDirectorOutput Out;
	FTrackedState S = BaseState(0.0);
	D->ForceState(EStreetballState::DribbleMoving, S);
	D->Describe(S, Out);
	TestTrue(TEXT("moving: hand +-1"), FMath::Abs(Out.Task[0]) == 1.f);
	TestEqual(TEXT("moving: apex 1.0"), Out.Task[1], 1.f);
	TestEqual(TEXT("moving: bounces_to_switch 0"), Out.Task[2], 0.f);
	TestTrue(TEXT("moving: speed in [1.5,2.5]"), Out.Task[3] >= 1.5f && Out.Task[3] <= 2.5f);
	TestTrue(TEXT("moving: direction is a unit vector"), FMath::IsNearlyEqual(FMath::Sqrt(Out.Task[4] * Out.Task[4] + Out.Task[5] * Out.Task[5]), 1.f, 1e-3f));
	TestTrue(TEXT("moving: distance in (0,10]"), Out.Task[6] > 0.f && Out.Task[6] <= 10.f);
	// JUMP_SHOT task: rim relative in heading frame, trigger 0 at start
	D->ForceState(EStreetballState::JumpShot, S);
	D->Describe(S, Out);
	TestTrue(TEXT("shot: rim ahead (+x) at 12.4 m"), FMath::IsNearlyEqual(Out.Task[0], 12.425f, 1e-3f) && FMath::IsNearlyEqual(Out.Task[1], 0.f, 1e-4f));
	TestTrue(TEXT("shot: rim 2.13 m above the pelvis"), FMath::IsNearlyEqual(Out.Task[2], 3.05f - 0.92f, 1e-3f));
	TestEqual(TEXT("shot: trigger off"), Out.Task[3], 0.f);
	D->RemoveFromRoot();
	return true;
}

// ---------------------------------------------------------------------------- end-to-end loop
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FStreetballLoopTest, "Streetball.C3.WorldLoop", PFlags)
bool FStreetballLoopTest::RunTest(const FString&)
{
	FScopedGameWorld TW;
	AStreetballWorld* W = TW.World->SpawnActor<AStreetballWorld>();
	if (!TestNotNull(TEXT("world"), W)) return false;
	if (!W->GetSim()) TestTrue(TEXT("Setup"), W->Setup(TW.World));
	TestEqual(TEXT("five policy families resolved"), W->GetPolicies().Num(), 5);
	int32 Null = 0;
	for (const TPair<FString, TObjectPtr<UPolicyRunner>>& P : W->GetPolicies()) if (!P.Value) ++Null;
	TestEqual(TEXT("every family has a runnable policy (trained or dummy)"), Null, 0);
	TestTrue(TEXT("transition table loaded from Content/Sim"), W->GetDirector()->HasTable());
	AddInfo(FString::Printf(TEXT("transition table v%d; trained policies present: [%s]"), W->GetDirector()->TableVersion(), *FString::Join(W->GetRealPolicyNames(), TEXT(", "))));
	TestNotNull(TEXT("camera pre-allocated"), W->GetCamera());

	// Run 1 s in STAND
	for (int32 i = 0; i < 50; ++i) W->StepControl();
	TestEqual(TEXT("STAND runs the balance family"), W->GetLastDirectorOutput().PolicyName, FString(TEXT("balance")));

	// UU_AGENT hand-over: prev_action passes through a policy switch unchanged
	const TArray<float> ActionBefore = W->GetLastAction();
	W->GetDirector()->ForceState(EStreetballState::Roam, W->GetTracker()->State());   // switch family without a reset
	W->StepControl();
	TestEqual(TEXT("switched to locomotion"), W->GetLastPolicyName(), FString(TEXT("locomotion")));
	const TArray<float>& ObsAfter = W->GetLastObs();
	double HandoverErr = 0.0;
	for (int32 k = 0; k < 27; ++k) HandoverErr = FMath::Max(HandoverErr, FMath::Abs((double)ObsAfter[63 + k] - ActionBefore[k]));
	TestTrue(TEXT("prev_action slots [63:90] equal the last action of the previous policy"), HandoverErr == 0.0 && ActionBefore.Num() == 27);
	AddInfo(FString::Printf(TEXT("hand-over prev_action max diff %.3e"), HandoverErr));
	W->GetDirector()->ForceState(EStreetballState::Stand, W->GetTracker()->State());

	// Jump to tier 3 with the ball at the hand; the dummy policy will not dribble, so control is
	// lost after 0.6 s, SCRAMBLE starts, and the 3 s countdown ends in a HARD_RESET.
	FStreetballResetSpec Spec; Spec.bRequested = true; Spec.Reason = TEXT("test: tier 3");
	W->GetDirector()->SetMastered(1, true); W->GetDirector()->SetMastered(2, true);
	W->GetDirector()->ForceState(EStreetballState::DribbleStationary, W->GetTracker()->State());
	W->ApplyReset(Spec);
	const int32 ResetsBefore = W->GetResetCount();
	bool SawScramble = false; int32 Steps = 0;
	while (Steps++ < 300 && W->GetResetCount() == ResetsBefore)
	{
		W->StepControl();
		if (W->GetDirector()->GetState() == EStreetballState::Scramble) SawScramble = true;
	}
	TestTrue(TEXT("SCRAMBLE was entered"), SawScramble);
	TestTrue(TEXT("countdown expiry produced a hard reset"), W->GetResetCount() > ResetsBefore);
	TestEqual(TEXT("after reset the tier-3 state resumes"), (int32)W->GetDirector()->GetState(), (int32)EStreetballState::DribbleStationary);
	AddInfo(FString::Printf(TEXT("scramble->reset after %d control steps (%.2f s); audio events seen so far: %d"), Steps, Steps * 0.02, W->GetRecentAudioEvents().Num()));
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS
