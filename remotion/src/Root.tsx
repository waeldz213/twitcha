import React from "react";
import { Composition } from "remotion";
import { ClipTemplate, ClipTemplateProps, CLIP_FPS } from "./ClipTemplate";

const DEFAULT_PROPS: ClipTemplateProps = {
  videoSrc: "",
  words: [],
  title: "Epic Moment",
  channelName: "@streamer",
  durationInFrames: 60 * CLIP_FPS, // 60 s
};

export const Root: React.FC = () => (
  <Composition
    id="ClipTemplate"
    component={ClipTemplate}
    durationInFrames={DEFAULT_PROPS.durationInFrames}
    fps={CLIP_FPS}
    width={1080}
    height={1920}
    defaultProps={DEFAULT_PROPS}
  />
);
