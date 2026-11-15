#pragma once

#include "CoreMinimal.h"

/**
 * Shared Profile B UMG/Slate design tokens for StreetballGym.
 * Mirrors standard RL UI rules: shared spacing, radii, legible typography,
 * policy palette (RED = heuristic bot, GREEN = reference RL, BLUE = custom),
 * safe-area margins, and minimum 48dp / 124px touch target sizing.
 */
namespace StreetballUiTheme
{
	inline constexpr float Space1 = 4.f;
	inline constexpr float Space2 = 8.f;
	inline constexpr float Space3 = 12.f;
	inline constexpr float Space4 = 16.f;
	inline constexpr float Space5 = 24.f;

	inline constexpr float RadiusS = 8.f;
	inline constexpr float RadiusM = 16.f;
	inline constexpr float RadiusL = 24.f;

	inline constexpr float SafeAreaMargin = 24.f;
	inline constexpr float TouchMinPx = 124.f;
	inline constexpr float TouchHeightMinPx = 48.f;

	inline constexpr int32 FontXS = 14;
	inline constexpr int32 FontS = 16;
	inline constexpr int32 FontM = 18;
	inline constexpr int32 FontL = 22;

	inline const FLinearColor Background(0.05f, 0.08f, 0.11f, 0.78f);
	inline const FLinearColor PanelBg(0.06f, 0.09f, 0.13f, 0.72f);
	inline const FLinearColor TextPrimary(1.f, 1.f, 1.f, 1.f);
	inline const FLinearColor TextMuted(0.75f, 0.80f, 0.82f, 1.f);
	inline const FLinearColor AccentGold(1.f, 0.85f, 0.30f, 1.f);

	// Standard RL policy badge palette
	inline const FLinearColor PolicyBot(1.f, 0.25f, 0.20f, 1.f);     // RED = heuristic bot / fallback
	inline const FLinearColor PolicyRef(0.16f, 0.55f, 0.28f, 1.f);   // GREEN = reference RL
	inline const FLinearColor PolicyCustom(0.20f, 0.50f, 1.f, 1.f);  // BLUE = custom / user
}
