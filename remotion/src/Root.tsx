import React from "react";
import { Composition } from "remotion";
import { ClipTemplate, ClipTemplateProps } from "./ClipTemplate";

const DEFAULT_PROPS: ClipTemplateProps = {
  videoSrc: "",
  words: [],
  title: "Epic Moment",
  channelName: "@streamer",
  durationInFrames: 1800, // 60 s × 30 fps
};

export const Root: React.FC = () => (
  <Composition
    id="ClipTemplate"
    component={ClipTemplate}
    durationInFrames={DEFAULT_PROPS.durationInFrames}
    fps={30}
    width={1080}
    height={1920}
    defaultProps={DEFAULT_PROPS}
  />
);
