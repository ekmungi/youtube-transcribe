import { describe, it, expect } from "vitest";
import { classifyYoutubeUrl } from "./url-classify";

describe("classifyYoutubeUrl", () => {
  it("classifies plain video URLs as video", () => {
    expect(classifyYoutubeUrl("https://www.youtube.com/watch?v=dQw4w9WgXcQ")).toBe("video");
    expect(classifyYoutubeUrl("https://youtu.be/dQw4w9WgXcQ")).toBe("video");
    expect(classifyYoutubeUrl("https://www.youtube.com/shorts/dQw4w9WgXcQ")).toBe("video");
  });

  it("classifies a watch URL with &list= as a single video", () => {
    // The user pointed at one specific video; the playlist is only context.
    expect(
      classifyYoutubeUrl("https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PLabc123")
    ).toBe("video");
  });

  it("classifies playlist URLs as playlist", () => {
    expect(classifyYoutubeUrl("https://www.youtube.com/playlist?list=PLabc123")).toBe("playlist");
    expect(classifyYoutubeUrl("https://www.youtube.com/watch?list=PLabc123")).toBe("playlist");
  });
});
