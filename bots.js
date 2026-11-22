/**
 * Horse Racing Bot Chat - Bot Definitions
 * 
 * Each bot has a personality bias but is free to decide:
 * - Tip a favourite if very confident
 * - Go each-way when the odds suit better
 * - Take a longshot if genuine value is spotted
 */

const BOTS = {
  BloodlineBetty: {
    id: "BloodlineBetty",
    name: "BloodlineBetty",
    colour: "#ec4899",          // pink
    emoji: "🧬",
    description: "Pedigree & breeding specialist. Loves horses with strong family records and early potential.",
    bias: {
      formWeight: 0.25,
      pedigreeWeight: 0.40,
      trainerWeight: 0.15,
      valueWeight: 0.20
    }
  },
  DevilAdvocate: {
    id: "DevilAdvocate",
    name: "DevilAdvocate",
    colour: "#a855f7",          // purple
    emoji: "😈",
    description: "Contrarian. Always questions the favourite and looks for holes in the obvious selection.",
    bias: {
      formWeight: 0.30,
      pedigreeWeight: 0.10,
      trainerWeight: 0.20,
      valueWeight: 0.40
    }
  },
  FormFox: {
    id: "FormFox",
    name: "FormFox",
    colour: "#3b82f6",          // blue
    emoji: "📊",
    description: "Pure form student. Recent runs, speed figures and consistency are everything.",
    bias: {
      formWeight: 0.55,
      pedigreeWeight: 0.05,
      trainerWeight: 0.15,
      valueWeight: 0.25
    }
  },
  HotTrainer: {
    id: "HotTrainer",
    name: "HotTrainer",
    colour: "#ef4444",          // red
    emoji: "🔥",
    description: "Follows in-form trainers and jockeys. Yard form and jockey bookings matter most.",
    bias: {
      formWeight: 0.20,
      pedigreeWeight: 0.10,
      trainerWeight: 0.50,
      valueWeight: 0.20
    }
  },
  PaceProphet: {
    id: "PaceProphet",
    name: "PaceProphet",
    colour: "#f97316",          // orange
    emoji: "⏱️",
    description: "Race shape specialist. Looks at likely pace, front-runners and how the race will unfold.",
    bias: {
      formWeight: 0.30,
      pedigreeWeight: 0.10,
      trainerWeight: 0.15,
      valueWeight: 0.45
    }
  },
  ValueHunter: {
    id: "ValueHunter",
    name: "ValueHunter",
    colour: "#22c55e",          // green
    emoji: "💰",
    description: "Odds vs probability. Only interested when the price is bigger than the chance of winning.",
    bias: {
      formWeight: 0.25,
      pedigreeWeight: 0.10,
      trainerWeight: 0.15,
      valueWeight: 0.50
    }
  }
};

/**
 * Decide tip type based on confidence and odds.
 * Returns: { type: "win" | "ew", confidence: number, reason: string }
 */
function decideTipType(bot, horse, estimatedProb, decimalOdds) {
  const impliedProb = 1 / decimalOdds;
  const edge = estimatedProb - impliedProb;
  const confidence = Math.round(estimatedProb * 100);

  // High confidence short-priced favourite → win tip
  if (decimalOdds <= 2.5 && estimatedProb >= 0.45) {
    return {
      type: "win",
      confidence,
      reason: "Strong favourite with high confidence"
    };
  }

  // Good each-way value (places available and edge on place)
  if (decimalOdds >= 4.0 && edge > 0.05) {
    return {
      type: "ew",
      confidence: Math.min(confidence, 75),
      reason: "Each-way value at the price"
    };
  }

  // Longshot with genuine edge
  if (decimalOdds >= 10 && edge > 0.08) {
    return {
      type: "win",
      confidence: Math.min(confidence, 55),
      reason: "Big-priced runner with positive edge"
    };
  }

  // Default: win if positive edge, otherwise still tip but lower confidence
  return {
    type: edge > 0 ? "win" : "win",
    confidence: Math.max(30, Math.min(confidence, 80)),
    reason: edge > 0 ? "Positive expected value" : "Best option on the card"
  };
}

/**
 * Simple scoring function used by generate_tips.py (mirrored here for reference)
 * In production the Python script does the heavy lifting.
 */
function scoreRunner(bot, runner) {
  // Placeholder – real scoring happens in generate_tips.py
  // This is only used if we ever run client-side tips
  let score = 0.5;

  if (runner.formScore) score += bot.bias.formWeight * runner.formScore;
  if (runner.pedigreeScore) score += bot.bias.pedigreeWeight * runner.pedigreeScore;
  if (runner.trainerScore) score += bot.bias.trainerWeight * runner.trainerScore;
  if (runner.valueScore) score += bot.bias.valueWeight * runner.valueScore;

  return Math.max(0.05, Math.min(0.95, score));
}

// Export for browser
if (typeof window !== "undefined") {
  window.BOTS = BOTS;
  window.decideTipType = decideTipType;
  window.scoreRunner = scoreRunner;
}
