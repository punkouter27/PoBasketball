#include "GrandmaVoice.h"
#include "StreetballGym.h"
#include "Components/AudioComponent.h"
#include "Components/SkeletalMeshComponent.h"
#include "GameFramework/Actor.h"
#include "Sound/SoundBase.h"

namespace
{
	struct FMoodShape { const TCHAR* Morph; float W; };
	// Expression layer per mood (CC morph names). Lip-sync columns from the bank are added on top.
	void MoodShapes(FName Mood, TArray<FMoodShape, TInlineAllocator<8>>& Out)
	{
		static const FName Happy(TEXT("happy")), Smug(TEXT("smug")), Annoyed(TEXT("annoyed")), Determined(TEXT("determined")), Surprised(TEXT("surprised"));
		if (Mood == Happy) { Out = { {TEXT("Mouth_Smile_L"), 0.55f}, {TEXT("Mouth_Smile_R"), 0.55f}, {TEXT("Cheek_Raise_L"), 0.4f}, {TEXT("Cheek_Raise_R"), 0.4f} }; }
		else if (Mood == Smug) { Out = { {TEXT("Mouth_Smile_L"), 0.5f}, {TEXT("Mouth_Smile_R"), 0.15f}, {TEXT("Brow_Raise_Outer_L"), 0.4f}, {TEXT("Eye_Squint_R"), 0.25f} }; }
		else if (Mood == Annoyed) { Out = { {TEXT("Brow_Drop_L"), 0.5f}, {TEXT("Brow_Drop_R"), 0.5f}, {TEXT("Nose_Sneer_L"), 0.2f}, {TEXT("Mouth_Press_L"), 0.25f}, {TEXT("Mouth_Press_R"), 0.25f} }; }
		else if (Mood == Determined) { Out = { {TEXT("Brow_Drop_L"), 0.35f}, {TEXT("Brow_Drop_R"), 0.35f}, {TEXT("Eye_Squint_L"), 0.3f}, {TEXT("Eye_Squint_R"), 0.3f} }; }
		else if (Mood == Surprised) { Out = { {TEXT("Brow_Raise_Inner_L"), 0.6f}, {TEXT("Brow_Raise_Inner_R"), 0.6f}, {TEXT("Brow_Raise_Outer_L"), 0.5f}, {TEXT("Brow_Raise_Outer_R"), 0.5f} }; }
		else Out.Reset();
	}
}

void FGrandmaVoicePlayer::Initialize(AActor* Owner, USkeletalMeshComponent* InFace, UGrandmaVoiceBank* InBank, int32 Seed)
{
	Bank = InBank;
	Face = InFace;
	Rng.Initialize(Seed * 7919 + 13);
	Active = INDEX_NONE; LastPicked = INDEX_NONE; StartT = -1.0; LastLineEndT = -100.0;
	NextBlinkT = 2.0 + Rng.FRand() * 2.0;
	MoodMorphs.Reset();
	if (Owner && InFace)
	{
		UAudioComponent* AC = NewObject<UAudioComponent>(Owner, TEXT("GrandmaVoice"));
		AC->bAutoActivate = false;
		AC->bAllowSpatialization = true;
		// Follow the head (the mesh is MuJoCo driven; attaching to a bone is cosmetic only).
		AC->SetupAttachment(InFace, InFace->DoesSocketExist(TEXT("head")) ? FName(TEXT("head")) : NAME_None);
		AC->RegisterComponent();
		Audio = AC;
	}
}

int32 FGrandmaVoicePlayer::PickLine(const UGrandmaVoiceBank& InBank, FName EventKey, FRandomStream& InRng, int32 AvoidIndex)
{
	int32 Count = 0;
	for (int32 i = 0; i < InBank.Lines.Num(); ++i) if (InBank.Lines[i].Event == EventKey && i != AvoidIndex) ++Count;
	if (Count == 0)
	{
		// only the avoided line exists: allow the repeat
		return (InBank.Lines.IsValidIndex(AvoidIndex) && InBank.Lines[AvoidIndex].Event == EventKey) ? AvoidIndex : INDEX_NONE;
	}
	int32 Pick = InRng.RandRange(0, Count - 1);
	for (int32 i = 0; i < InBank.Lines.Num(); ++i)
	{
		if (InBank.Lines[i].Event != EventKey || i == AvoidIndex) continue;
		if (Pick-- == 0) return i;
	}
	return INDEX_NONE;
}

float FGrandmaVoicePlayer::SampleMorph(const UGrandmaVoiceBank& InBank, const FGrandmaVoiceLine& Line, int32 MorphIndex, float T)
{
	const int32 NM = InBank.Morphs.Num();
	if (NM == 0 || Line.NumFrames <= 0 || Line.Frames.Num() < Line.NumFrames * NM || MorphIndex < 0 || MorphIndex >= NM) return 0.f;
	const float F = FMath::Clamp(T * InBank.Fps, 0.f, (float)(Line.NumFrames - 1));
	const int32 F0 = FMath::FloorToInt(F);
	const int32 F1 = FMath::Min(F0 + 1, Line.NumFrames - 1);
	const float A = F - F0;
	return FMath::Lerp(Line.Frames[F0 * NM + MorphIndex], Line.Frames[F1 * NM + MorphIndex], A);
}

const FGrandmaVoiceLine* FGrandmaVoicePlayer::OnEvent(EPresentationEvent E, double GameTime)
{
	UGrandmaVoiceBank* B = Bank.Get();
	const TCHAR* Key = FPresentationEventDetector::VoiceKey(E);
	if (!B || !Key) return nullptr;
	// a line is still playing, or the gap since the last one is too short
	if (Active != INDEX_NONE || GameTime - LastLineEndT < B->MinGapS) return nullptr;
	const int32 Idx = PickLine(*B, FName(Key), Rng, LastPicked);
	if (Idx == INDEX_NONE) return nullptr;
	const FGrandmaVoiceLine& L = B->Lines[Idx];
	Active = Idx; LastPicked = Idx; StartT = GameTime;
	Mood = L.Mood; MoodWeight = 1.f;
	Subtitle = L.Text;
	SubtitleUntil = GameTime + FMath::Max(L.Duration, 1.5f) + 0.8;
	++LinesPlayed;
	if (UAudioComponent* AC = Audio.Get())
	{
		if (L.Sound)
		{
			AC->SetSound(L.Sound);
			AC->SetVolumeMultiplier(B->VolumeMultiplier);
			AC->Play();
		}
	}
	UE_LOG(LogStreetball, Log, TEXT("Voice: %s -> %s \"%s\""), Key, *L.Id.ToString(), *L.Text);
	return &L;
}

void FGrandmaVoicePlayer::ApplyMood(FName InMood, float Strength)
{
	USkeletalMeshComponent* F = Face.Get();
	if (!F) return;
	for (const FName& M : MoodMorphs) F->SetMorphTarget(M, 0.f, false);
	MoodMorphs.Reset();
	TArray<FMoodShape, TInlineAllocator<8>> Shapes;
	MoodShapes(InMood, Shapes);
	for (const FMoodShape& S : Shapes)
	{
		const FName N(S.Morph);
		F->SetMorphTarget(N, S.W * Strength, false);
		MoodMorphs.Add(N);
	}
}

void FGrandmaVoicePlayer::Tick(double GameTime, float DeltaSeconds)
{
	USkeletalMeshComponent* F = Face.Get();
	UGrandmaVoiceBank* B = Bank.Get();
	if (!F) return;

	// mood layer: the baked track already carries the expression while a line plays; afterwards the mood
	// lingers and fades over ~2.5 s so the face does not snap back to neutral.
	if (Active == INDEX_NONE && MoodWeight > 0.f)
	{
		MoodWeight = FMath::Max(0.f, MoodWeight - DeltaSeconds / 2.5f);
		ApplyMood(MoodWeight > 0.f ? Mood : NAME_None, MoodWeight);
	}
	else if (Active != INDEX_NONE && MoodMorphs.Num() > 0)
	{
		ApplyMood(NAME_None, 0.f);
	}

	// lip-sync from the baked track
	if (B && Active != INDEX_NONE && B->Lines.IsValidIndex(Active))
	{
		const FGrandmaVoiceLine& L = B->Lines[Active];
		const float T = (float)(GameTime - StartT);
		const bool bDone = T > L.Duration + 0.1f;
		for (int32 m = 0; m < B->Morphs.Num(); ++m)
		{
			// blinks are owned by the blink layer below
			if (B->Morphs[m] == TEXT("Eye_Blink_L") || B->Morphs[m] == TEXT("Eye_Blink_R")) continue;
			const float W = bDone ? 0.f : SampleMorph(*B, L, m, T);
			F->SetMorphTarget(B->Morphs[m], FMath::Clamp(W, 0.f, 1.f), false);
		}
		if (bDone) { Active = INDEX_NONE; LastLineEndT = GameTime; }
	}

	// blinks every 2.5-5 s, 150 ms
	if (BlinkT < 0.0 && GameTime >= NextBlinkT) BlinkT = GameTime;
	float Blink = 0.f;
	if (BlinkT >= 0.0)
	{
		const float U = (float)((GameTime - BlinkT) / 0.15);
		Blink = U < 1.f ? FMath::Sin(U * PI) : 0.f;
		if (U >= 1.f) { BlinkT = -1.0; NextBlinkT = GameTime + 2.5 + Rng.FRand() * 2.5; }
	}
	F->SetMorphTarget(TEXT("Eye_Blink_L"), Blink, false);
	F->SetMorphTarget(TEXT("Eye_Blink_R"), Blink, false);
}
