/**
 * ClipTemplate – main Remotion composition for short-form clip rendering.
 *
 * Layout (1080 × 1920, 9:16):
 *   ┌──────────────────────┐
 *   │  Channel branding    │  ← top 120 px
 *   │                      │
 *   │     Video (fill)     │
 *   │                      │
 *   │  Animated subtitles  │  ← bottom 30 % of frame
 *   │  Title / CTA         │  ← bottom 80 px
 *   └──────────────────────┘
 */
import React from "react";
import {
  AbsoluteFill,
  Audio,
  Img,
  interpolate,
  Sequence,
  spring,
  useCurrentFrame,
  useVideoConfig,
  Video,
} from "remotion";

// ── Types ────────────────────────────────────────────────────────────────────

export interface WordTimestamp {
  word: string;
  start: number; // seconds
  end: number;   // seconds
  confidence?: number;
}

export interface ClipTemplateProps {
  videoSrc: string;
  words: WordTimestamp[];
  title: string;
  channelName: string;
  durationInFrames: number;
  logoSrc?: string;
}

// ── Helpers ──────────────────────────────────────────────────────────────────

const WORDS_PER_GROUP = 4;

function groupWords(
  words: WordTimestamp[]
): { text: string; startFrame: number; endFrame: number }[] {
  const groups: { text: string; startFrame: number; endFrame: number }[] = [];
  for (let i = 0; i < words.length; i += WORDS_PER_GROUP) {
    const chunk = words.slice(i, i + WORDS_PER_GROUP);
    groups.push({
      text: chunk.map((w) => w.word).join(" "),
      startFrame: Math.round(chunk[0].start * 30),
      endFrame: Math.round(chunk[chunk.length - 1].end * 30) + 5,
    });
  }
  return groups;
}

// ── Sub-components ────────────────────────────────────────────────────────────

const SubtitleWord: React.FC<{ text: string }> = ({ text }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const scale = spring({
    frame,
    fps,
    config: { damping: 8, stiffness: 200, mass: 0.5 },
  });

  return (
    <span
      style={{
        display: "inline-block",
        transform: `scale(${scale})`,
        transformOrigin: "center bottom",
        margin: "0 4px",
        textShadow: "2px 2px 8px rgba(0,0,0,0.9), -1px -1px 4px rgba(0,0,0,0.9)",
      }}
    >
      {text}
    </span>
  );
};

const SubtitleLine: React.FC<{
  text: string;
  startFrame: number;
  endFrame: number;
}> = ({ text, startFrame, endFrame }) => {
  const frame = useCurrentFrame();
  const opacity = interpolate(frame, [0, 3, endFrame - startFrame - 3, endFrame - startFrame], [0, 1, 1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <Sequence from={startFrame} durationInFrames={endFrame - startFrame}>
      <AbsoluteFill
        style={{
          justifyContent: "flex-end",
          alignItems: "center",
          paddingBottom: 160,
        }}
      >
        <div
          style={{
            opacity,
            fontSize: 64,
            fontWeight: 900,
            fontFamily: "'Arial Black', Arial, sans-serif",
            color: "#FFFFFF",
            textAlign: "center",
            maxWidth: 960,
            lineHeight: 1.25,
            letterSpacing: "0.01em",
            padding: "12px 24px",
            background: "rgba(0,0,0,0.35)",
            borderRadius: 16,
            backdropFilter: "blur(4px)",
          }}
        >
          {text.split(" ").map((word, idx) => (
            <SubtitleWord key={idx} text={word} />
          ))}
        </div>
      </AbsoluteFill>
    </Sequence>
  );
};

const BrandingBar: React.FC<{ channelName: string; logoSrc?: string }> = ({
  channelName,
  logoSrc,
}) => (
  <AbsoluteFill
    style={{
      justifyContent: "flex-start",
      alignItems: "flex-start",
      padding: "40px 48px",
      pointerEvents: "none",
    }}
  >
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 16,
        background: "rgba(0,0,0,0.55)",
        borderRadius: 40,
        padding: "10px 24px",
        backdropFilter: "blur(8px)",
      }}
    >
      {logoSrc && (
        <Img
          src={logoSrc}
          style={{ width: 48, height: 48, borderRadius: "50%", objectFit: "cover" }}
        />
      )}
      <span
        style={{
          color: "#FFFFFF",
          fontFamily: "'Arial Black', Arial, sans-serif",
          fontWeight: 700,
          fontSize: 36,
          letterSpacing: "0.03em",
        }}
      >
        {channelName}
      </span>
    </div>
  </AbsoluteFill>
);

const TitleBar: React.FC<{ title: string }> = ({ title }) => {
  const frame = useCurrentFrame();
  const opacity = interpolate(frame, [0, 15], [0, 1], { extrapolateRight: "clamp" });

  return (
    <AbsoluteFill
      style={{
        justifyContent: "flex-end",
        alignItems: "center",
        paddingBottom: 48,
        pointerEvents: "none",
        opacity,
      }}
    >
      <div
        style={{
          fontSize: 42,
          fontWeight: 800,
          fontFamily: "'Arial Black', Arial, sans-serif",
          color: "#FFD700",
          textAlign: "center",
          maxWidth: 960,
          textShadow: "2px 2px 6px rgba(0,0,0,0.8)",
          padding: "0 32px",
        }}
      >
        {title}
      </div>
    </AbsoluteFill>
  );
};

// ── Main composition ─────────────────────────────────────────────────────────

export const ClipTemplate: React.FC<ClipTemplateProps> = ({
  videoSrc,
  words,
  title,
  channelName,
  logoSrc,
}) => {
  const subtitleGroups = groupWords(words);

  return (
    <AbsoluteFill style={{ background: "#000" }}>
      {/* Background video */}
      {videoSrc && (
        <Video
          src={videoSrc}
          style={{ width: "100%", height: "100%", objectFit: "cover" }}
        />
      )}

      {/* Branding overlay (top) */}
      <BrandingBar channelName={channelName} logoSrc={logoSrc} />

      {/* Animated subtitle lines */}
      {subtitleGroups.map((group, idx) => (
        <SubtitleLine
          key={idx}
          text={group.text}
          startFrame={group.startFrame}
          endFrame={group.endFrame}
        />
      ))}

      {/* Title bar (bottom) */}
      <TitleBar title={title} />
    </AbsoluteFill>
  );
};
