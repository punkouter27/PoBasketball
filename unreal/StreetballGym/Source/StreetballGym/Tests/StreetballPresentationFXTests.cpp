// Presentation layer (plugins pass, 2026-11-17): event detection, VFX mapping, voice selection/lip-sync sampling,
// asset wiring, and the guarantee that none of it changes the simulation.
#include "Misc/AutomationTest.h"

#if WITH_DEV_AUTOMATION_TESTS

#include "StreetballGym.h"
#include "StreetballWorld.h"
#include "PresentationEvents.h"
#include "CourtFX.h"
#include "GrandmaVoice.h"
#include "MuJoCoSim.h"
#include "Engine/Engine.h"
#include "Engine/World.h"

namespace
{
	constexpr EAutomationTestFlags FXFlags = EAutomationTestFlags::EditorContext | EAutomationTestFlags::ProductFilter;

	struct FFxTestWorld
	{
		UWorld* World = nullptr;
		FFxTestWorld()
		{
			World = UWorld::CreateWorld(EWorldType::Game, false, TEXT("StreetballFXTestWorld"));
			FWorldContext& Ctx = GEngine->CreateNewWorldContext(EWorldType::Game);
			Ctx.SetCurrentWorld(World);
			World->InitializeActorsForPlay(FURL());
			World->BeginPlay();
		}
		~FFxTestWorld()
		{
			if (World) { GEngine->DestroyWorldContext(World); World->DestroyWorld(false); }
		}
	};

	FTrackedState State(double T)
	{
		FTrackedState S;
		S.Time = T;
		S.PelvisPos = FVector3d(0, 0, 0.92);
		S.FootFloor[0] = S.FootFloor[1] = true;
		S.RimPos[0] = FVector3d(12.425, 0, 3.05); S.RimPos[1] = FVector3d(-12.425, 0, 3.05);
		S.InControl = true;
		return S;
	}

	int32 Count(const TArray<EPresentationEvent>& E, EPresentationEvent X)
	{
		int32 N = 0;
		for (EPresentationEvent e : E) N += (e == X) ? 1 : 0;
		return N;
	}
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FStreetballEventDetectorTest, "Streetball.Presentation.EventDetector", FXFlags)
bool FStreetballEventDetectorTest::RunTest(const FString&)
{
	FPresentationEventDetector D;
	FStreetballDirectorOutput Dir;
	FStreetballProgress P; P.ActiveTier = 5;
	TArray<EPresentationEvent> Out;
	double T = 0.0;
	auto Step = [&](const FTrackedState& S, EStreetballState St) { Out.Reset(); D.Update(S, Dir, P, St, Out); };

	Step(State(T), EStreetballState::JumpShot);                              // primes, no events
	TestEqual(TEXT("first update only primes"), Out.Num(), 0);

	// clean make: no rim contact since the shot started
	P.ShotsTaken = 1; P.ShotsMade = 1;
	Step(State(T += 0.02), EStreetballState::HardReset);
	TestEqual(TEXT("make"), Count(Out, EPresentationEvent::Make), 1);
	TestEqual(TEXT("swish (no rim)"), Count(Out, EPresentationEvent::Swish), 1);

	// rim-out miss
	Step(State(T += 0.02), EStreetballState::JumpShot);
	FTrackedState Rim = State(T += 0.02); Rim.BallRim = true;
	Step(Rim, EStreetballState::JumpShot);
	P.ShotsTaken = 2;
	Step(State(T += 0.02), EStreetballState::HardReset);
	TestEqual(TEXT("miss"), Count(Out, EPresentationEvent::Miss), 1);
	TestEqual(TEXT("rim out"), Count(Out, EPresentationEvent::RimOut), 1);
	TestEqual(TEXT("no make on a miss"), Count(Out, EPresentationEvent::Make), 0);

	// scramble start -> save
	P.ActiveTier = 4;
	Step(State(T += 0.02), EStreetballState::DribbleMoving);
	Step(State(T += 0.02), EStreetballState::Scramble);
	TestEqual(TEXT("scramble start"), Count(Out, EPresentationEvent::ScrambleStart), 1);
	Step(State(T += 0.02), EStreetballState::DribbleMoving);
	TestEqual(TEXT("scramble save"), Count(Out, EPresentationEvent::ScrambleSave), 1);

	// scramble that ends in a hard reset is not a save
	Step(State(T += 0.02), EStreetballState::Scramble);
	Dir.Reset.bRequested = true; Dir.Reset.Reason = TEXT("scramble countdown expired");
	Step(State(T += 0.02), EStreetballState::HardReset);
	TestEqual(TEXT("expired scramble is no save"), Count(Out, EPresentationEvent::ScrambleSave), 0);
	Dir.Reset = FStreetballResetSpec();

	// fall reason literal
	Dir.Reset.bRequested = true; Dir.Reset.Reason = TEXT("fallen");
	Step(State(T += 0.02), EStreetballState::HardReset);
	TestEqual(TEXT("fall"), Count(Out, EPresentationEvent::Fall), 1);
	Dir.Reset = FStreetballResetSpec();

	// crossover + tier up
	P.HandSwitches = 1; P.Mastered[3] = true;
	Step(State(T += 0.02), EStreetballState::DribbleMoving);
	TestEqual(TEXT("crossover"), Count(Out, EPresentationEvent::Crossover), 1);
	TestEqual(TEXT("tier up"), Count(Out, EPresentationEvent::TierUp), 1);

	// jump: rising edge only
	FTrackedState Air = State(T += 0.02); Air.PelvisVel.Z = 1.6; Air.FootFloor[0] = Air.FootFloor[1] = false;
	Step(Air, EStreetballState::DribbleMoving);
	TestEqual(TEXT("jump fires"), Count(Out, EPresentationEvent::Jump), 1);
	Air.Time = T += 0.02;
	Step(Air, EStreetballState::DribbleMoving);
	TestEqual(TEXT("jump fires once per airtime"), Count(Out, EPresentationEvent::Jump), 0);

	// idle chatter after IdleAfterS of silence while dribbling
	int32 Idle = 0;
	for (int32 i = 0; i < (int32)(30.0 / 0.02); ++i) { Step(State(T += 0.02), EStreetballState::DribbleStationary); Idle += Count(Out, EPresentationEvent::Idle); }
	TestEqual(TEXT("one idle line in 30 s of quiet dribbling"), Idle, 1);
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FStreetballFXMappingTest, "Streetball.Presentation.FXMapping", FXFlags)
bool FStreetballFXMappingTest::RunTest(const FString&)
{
	FCourtFXMapping M;
	FCourtAudioEvent E; FCourtFXCue C;
	E.Kind = ECourtSound::BallFloor; E.Speed = 0.5f;
	TestFalse(TEXT("soft dribble: no dust"), M.FromAudioEvent(E, C));
	E.Speed = 6.f; E.PositionUE = FVector(100, 200, 0);
	TestTrue(TEXT("hard bounce: dust"), M.FromAudioEvent(E, C) && C.Fx == ECourtFX::BallDust);
	TestTrue(TEXT("dust at the contact"), C.PositionUE.Equals(FVector(100, 200, 0)));
	const float Hard = C.Scale;
	E.Speed = 2.f; M.FromAudioEvent(E, C);
	TestTrue(TEXT("dust scales with impact"), C.Scale < Hard);
	E.Kind = ECourtSound::BallRim; E.Speed = 1.f;
	TestFalse(TEXT("gentle rim roll: no sparks"), M.FromAudioEvent(E, C));
	E.Speed = 7.f;
	TestTrue(TEXT("hard rim: sparks"), M.FromAudioEvent(E, C) && C.Fx == ECourtFX::RimSparks);
	E.Kind = ECourtSound::NetRattle;
	TestTrue(TEXT("score: swish burst"), M.FromAudioEvent(E, C) && C.Fx == ECourtFX::Swish);
	E.Kind = ECourtSound::BallPalm;
	TestFalse(TEXT("palm touches: no effect"), M.FromAudioEvent(E, C));
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FStreetballVoicePickTest, "Streetball.Presentation.VoiceSelection", FXFlags)
bool FStreetballVoicePickTest::RunTest(const FString&)
{
	UGrandmaVoiceBank* B = NewObject<UGrandmaVoiceBank>(GetTransientPackage());
	B->Fps = 30.f;
	B->Morphs = { TEXT("Jaw_Open"), TEXT("Mouth_Smile_L") };
	for (int32 i = 0; i < 3; ++i)
	{
		FGrandmaVoiceLine& L = B->Lines.AddDefaulted_GetRef();
		L.Id = *FString::Printf(TEXT("make_%02d"), i); L.Event = TEXT("make"); L.Duration = 0.1f; L.NumFrames = 3;
		L.Frames = { 0.f, 0.f, 0.6f, 0.2f, 0.f, 0.4f };
	}
	FGrandmaVoiceLine& Miss = B->Lines.AddDefaulted_GetRef();
	Miss.Id = TEXT("miss_00"); Miss.Event = TEXT("miss"); Miss.NumFrames = 1; Miss.Frames = { 0.f, 0.f };

	FRandomStream R(1);
	int32 Last = INDEX_NONE, Repeats = 0;
	for (int32 i = 0; i < 50; ++i)
	{
		const int32 Pick = FGrandmaVoicePlayer::PickLine(*B, TEXT("make"), R, Last);
		TestTrue(TEXT("pick is a make line"), B->Lines.IsValidIndex(Pick) && B->Lines[Pick].Event == TEXT("make"));
		Repeats += (Pick == Last) ? 1 : 0;
		Last = Pick;
	}
	TestEqual(TEXT("never the same line twice in a row"), Repeats, 0);
	TestEqual(TEXT("single-line event may repeat"), FGrandmaVoicePlayer::PickLine(*B, TEXT("miss"), R, 3), 3);
	TestEqual(TEXT("unknown event"), FGrandmaVoicePlayer::PickLine(*B, TEXT("swish"), R, INDEX_NONE), (int32)INDEX_NONE);

	const FGrandmaVoiceLine& L0 = B->Lines[0];
	TestTrue(TEXT("frame 1 sample"), FMath::IsNearlyEqual(FGrandmaVoicePlayer::SampleMorph(*B, L0, 0, 1.f / 30.f), 0.6f, 1e-4f));
	TestTrue(TEXT("interpolates between frames"), FMath::IsNearlyEqual(FGrandmaVoicePlayer::SampleMorph(*B, L0, 0, 0.5f / 30.f), 0.3f, 1e-4f));
	TestTrue(TEXT("clamps past the end"), FMath::IsNearlyEqual(FGrandmaVoicePlayer::SampleMorph(*B, L0, 1, 5.f), 0.4f, 1e-4f));
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FStreetballPresentationWiringTest, "Streetball.Presentation.AssetsAndSimInvariance", FXFlags)
bool FStreetballPresentationWiringTest::RunTest(const FString&)
{
	FFxTestWorld TW;
	auto Make = [&](bool bPresentation) -> AStreetballWorld*
	{
		AStreetballWorld* W = TW.World->SpawnActorDeferred<AStreetballWorld>(AStreetballWorld::StaticClass(), FTransform::Identity);
		W->bPresentation = bPresentation;
		W->FinishSpawning(FTransform::Identity);
		if (!W->GetSim()) W->Setup(TW.World);
		return W;
	};
	AStreetballWorld* On = Make(true);
	AStreetballWorld* Off = Make(false);
	if (!TestNotNull(TEXT("worlds"), On) || !TestNotNull(TEXT("worlds"), Off) || !On->GetSim() || !Off->GetSim()) return false;

	// assets produced by Scripts/make_*.py / import_*.py / build_*.py
	TestTrue(TEXT("Niagara FX bank loaded (make_niagara_fx.py)"), On->GetFXPlayer().HasBank());
	TestTrue(TEXT("voice bank has the baked lines (import_voice_bank.py)"), On->GetVoice().HasBank());
	TestTrue(TEXT("Substrate court materials applied (make_court_materials.py)"), On->GetMaterialOverrideCount() >= 30);
	TestEqual(TEXT("presentation off: no material overrides"), Off->GetMaterialOverrideCount(), 0);
	AddInfo(FString::Printf(TEXT("material overrides %d, cloth %s, grooms %d"), On->GetMaterialOverrideCount(),
		On->GetCharacter()->HasCloth() ? TEXT("yes") : TEXT("no"), On->GetCharacter()->NumGrooms()));

	// identical sims with and without the presentation layer (it only listens)
	for (int32 i = 0; i < 150; ++i)
	{
		On->StepControl(); Off->StepControl();
		On->Tick(0.f); Off->Tick(0.f);       // drains presentation events; a zero delta never advances the clock
	}
	const TConstArrayView<double> QA = On->GetSim()->QPos();
	const TConstArrayView<double> QB = Off->GetSim()->QPos();
	double MaxDiff = 0.0;
	for (int32 i = 0; i < QA.Num(); ++i) MaxDiff = FMath::Max(MaxDiff, FMath::Abs(QA[i] - QB[i]));
	TestTrue(TEXT("qpos identical with presentation on/off after 3 s"), MaxDiff == 0.0);
	AddInfo(FString::Printf(TEXT("max |qpos on - off| = %.3e over %d dofs; FX bursts %d, net kicks %d"), MaxDiff, QA.Num(),
		On->GetFXPlayer().PlayedCount, On->GetFXPlayer().NetKicks));
	return true;
}

#endif
