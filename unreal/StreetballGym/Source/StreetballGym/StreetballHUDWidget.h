#pragma once

#include "CoreMinimal.h"
#include "Blueprint/UserWidget.h"
#include "StreetballDirector.h"
#include "StreetballHUDWidget.generated.h"

class UTextBlock;
class UProgressBar;
class UVerticalBox;
class UButton;
class UBorder;

/** Live numbers for the Dribble Lab panel (filled by the world each frame; the panel redraws at 10 Hz). */
struct FStreetballDribbleStats
{
	int32 Behaviour = 0;
	int32 Skin = 0;
	bool bTrained = false;
	bool bRightHand = true;
	bool bScramble = false;
	bool bLoose = false;
	int32 Resets = 0;
	int32 Bounces = 0;
	int32 CleanBounces = 0;
	int32 Streak = 0;
	int32 HandSwitches = 0;
	float RunS = 0.f;
	float BestRunS = 0.f;
};

/** Panel button pressed: Kind 0 = dribble behaviour, 1 = humanoid; Index into the lists given to SetDribbleFocus. */
DECLARE_MULTICAST_DELEGATE_TwoParams(FStreetballDribbleUiRequest, int32 /*Kind*/, int32 /*Index*/);

/**
 * PRD section 6 scoreboard, built entirely in C++ (no UMG asset): active tier, clean-dribble
 * streak, cumulative distance, milestone bar with checkmarks + % progress, and a countdown
 * ring (drawn in NativePaint) that is visible only while the ball is loose.
 */
UCLASS()
class STREETBALLGYM_API UStreetballHUDWidget : public UUserWidget
{
	GENERATED_BODY()

public:
	void UpdateFromProgress(const FStreetballProgress& P, EStreetballState State);
	void UpdateTelemetry(const FString& ModeLabel, const FString& CameraLabel, const FString& PolicyLabel,
	                     int32 Seed, float EpisodeReward, int32 NanInfCount, float Fps, bool bPaused, bool bFallbackPolicy,
	                     float Exertion01 = 0.f, float PowerW = 0.f, float TimeScale = 1.f);
	void SetModeHint(const FString& HintText);
	void SetTelemetryVisible(bool bVisible);
	/** Grandma voice subtitle above the bottom bar; empty hides it. */
	void SetSubtitle(const FString& Text);
	FString GetSubtitle() const;
	bool IsTelemetryVisible() const { return bTelemetryVisible; }
	/** Trigger a GPU-cheap Slate screen wipe on camera cuts or demo mode transitions. */
	void TriggerScreenWipe(float DurationS = 0.18f);
	/** Trigger a brief accent highlight on HUD badges when user input fires an action. */
	void TriggerInputPulse();
	/** Version stamp yyMMdd (UTC date of the HEAD commit, from StreetballGym.Build.cs). */
	static FString BuildStampYYMMDD();
	/** Text shown bottom-right ("build YYMMDD"); empty until the widget tree exists. */
	FString GetBuildStampText() const;
	/** true when the narrow (portrait) layout is in use. */
	bool IsNarrowLayout() const { return LayoutMode == 1; }
	/** Below this width (Slate units) the HUD uses the stacked narrow layout. */
	static constexpr float NarrowWidth = 900.f;
	/** Wide (landscape): corner anchors. Narrow (portrait / phone width): the mode banner, policy badge, telemetry and
	 *  key hints stack bottom-left above the version stamp and wrap, so nothing overlaps at 9:16. */
	void ApplyLayout(const FVector2D& ViewSize);

	/**
	 * Dribble Lab (2026-11-24): a clickable top-left panel (behaviour buttons, humanoid buttons, live dribble stats)
	 * replaces the five-tier scoreboard, milestone bar and mode banner, which are hidden (not removed). Buttons are
	 * built once here; nothing is created per frame. Keys 1-4 / H do the same as the buttons (world input).
	 */
	void SetDribbleFocus(const TArray<FString>& Behaviours, const TArray<bool>& Trained, const TArray<FString>& Skins);
	bool IsDribbleFocus() const { return DribblePanel != nullptr; }
	void UpdateDribbleStats(const FStreetballDribbleStats& S);
	bool IsPointerOverDribblePanel() const;
	FStreetballDribbleUiRequest OnDribbleUiRequest;
	static constexpr int32 MaxDribbleButtons = 6;
	// exposed for tests
	FString GetDribbleStatsText() const { return CachedDribbleStats; }
	int32 GetActiveBehaviourButton() const { return ShownBehaviour; }
	int32 GetActiveSkinButton() const { return ShownSkin; }
	FString GetTierText() const;
	FString GetStreakText() const;
	FString GetDistanceText() const;
	FString GetMilestoneText() const;
	float GetProgressPercent() const;
	bool IsCountdownVisible() const { return bLoose; }
	float GetCountdownFrac() const { return CountdownFrac; }

protected:
	virtual TSharedRef<SWidget> RebuildWidget() override;
	virtual void NativeTick(const FGeometry& MyGeometry, float InDeltaTime) override;
	virtual int32 NativePaint(const FPaintArgs& Args, const FGeometry& AllottedGeometry, const FSlateRect& MyCullingRect,
	                          FSlateWindowElementList& OutDrawElements, int32 LayerId, const FWidgetStyle& InWidgetStyle, bool bParentEnabled) const override;

	UPROPERTY() TObjectPtr<UVerticalBox> Root;
	UPROPERTY() TObjectPtr<UTextBlock> TierText;
	UPROPERTY() TObjectPtr<UTextBlock> StateText;
	UPROPERTY() TObjectPtr<UTextBlock> StreakText;
	UPROPERTY() TObjectPtr<UTextBlock> DistanceText;
	UPROPERTY() TObjectPtr<UTextBlock> MilestoneText;
	UPROPERTY() TObjectPtr<UTextBlock> CountdownText;
	UPROPERTY() TObjectPtr<UTextBlock> ProgressBarLabel;
	UPROPERTY() TObjectPtr<UProgressBar> ProgressBar;
	UPROPERTY() TObjectPtr<UTextBlock> StampText;
	UPROPERTY() TObjectPtr<UTextBlock> ModeBannerText;
	UPROPERTY() TObjectPtr<UTextBlock> PolicyFpsText;
	UPROPERTY() TObjectPtr<UTextBlock> TelemetryText;
	UPROPERTY() TObjectPtr<UTextBlock> BottomBarText;
	UPROPERTY() TObjectPtr<UTextBlock> SubtitleText;
	FString LastSubtitle;
	int32 LayoutMode = -1;   // -1 not laid out yet, 0 wide, 1 narrow
	float LayoutWidth = 0.f;

	bool bLoose = false;
	bool bTelemetryVisible = false;
	bool bTelemetryDirty = true;
	double LastTelemetryUpdateS = -1.0;
	FString LastModeLabel, LastCameraLabel, LastPolicyLabel, LastModeHint;
	bool bLastPaused = false;
	bool bLastFallbackPolicy = false;
	float LastTimeScale = 1.f;
	float CountdownFrac = 1.f;
	float ProgressPercent = 0.f;
	float DisplayedProgress01 = 0.f;
	float TargetProgress01 = 0.f;
	int32 LastTierNum = -1;
	float TierPopTimer = 0.f;
	float SubtitleFadeAlpha = 0.f;
	float WipeTimer = 0.f;
	float WipeDuration = 0.18f;
	float InputPulseTimer = 0.f;
	FString CachedTier, CachedStreak, CachedDistance, CachedMilestone;

	// Dribble Lab
	UFUNCTION() void OnBehaviour0() { RequestDribble(0, 0); }
	UFUNCTION() void OnBehaviour1() { RequestDribble(0, 1); }
	UFUNCTION() void OnBehaviour2() { RequestDribble(0, 2); }
	UFUNCTION() void OnBehaviour3() { RequestDribble(0, 3); }
	UFUNCTION() void OnBehaviour4() { RequestDribble(0, 4); }
	UFUNCTION() void OnBehaviour5() { RequestDribble(0, 5); }
	UFUNCTION() void OnSkin0() { RequestDribble(1, 0); }
	UFUNCTION() void OnSkin1() { RequestDribble(1, 1); }
	UFUNCTION() void OnSkin2() { RequestDribble(1, 2); }
	UFUNCTION() void OnSkin3() { RequestDribble(1, 3); }
	UFUNCTION() void OnSkin4() { RequestDribble(1, 4); }
	UFUNCTION() void OnSkin5() { RequestDribble(1, 5); }
	void RequestDribble(int32 Kind, int32 Index);
	UButton* MakeDribbleButton(UVerticalBox* Box, const FString& Label, int32 Kind, int32 Index, TArray<TObjectPtr<UTextBlock>>& OutLabels);
	void StyleDribbleButtons(TArray<TObjectPtr<UButton>>& Buttons, TArray<TObjectPtr<UTextBlock>>& Labels, int32 Active);
	UPROPERTY() TObjectPtr<UBorder> DribblePanel;
	UPROPERTY() TArray<TObjectPtr<UButton>> BehaviourButtons;
	UPROPERTY() TArray<TObjectPtr<UTextBlock>> BehaviourLabels;
	UPROPERTY() TArray<TObjectPtr<UButton>> SkinButtons;
	UPROPERTY() TArray<TObjectPtr<UTextBlock>> SkinLabels;
	UPROPERTY() TObjectPtr<UTextBlock> DribbleStatsText;
	UPROPERTY() TObjectPtr<UTextBlock> DribbleStatusText;
	TArray<bool> BehaviourTrained;
	TArray<FString> BehaviourNames;
	int32 ShownBehaviour = -1;
	int32 ShownSkin = -1;
	double LastDribbleStatsS = -1.0;
	FString CachedDribbleStats;
};
