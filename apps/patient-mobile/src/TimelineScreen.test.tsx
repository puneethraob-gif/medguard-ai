import React from "react";
import renderer, { act, type ReactTestInstance, type ReactTestRenderer } from "react-test-renderer";
import { Pressable, Text } from "react-native";
import TimelineScreen, { NextStepsCard, type TimelineEvent } from "./TimelineScreen";

const event: TimelineEvent = {
  id: 41,
  event_type: "test_scheduled",
  title: "Laboratory test scheduled",
  description: "A test was scheduled by your care team.",
  event_date: "2030-06-18T09:00:00+00:00",
  source_module: "laboratory",
  status: "scheduled",
};

describe("patient healthcare timeline", () => {
  it("loads actual timeline entries, filters by category, and opens event details", async () => {
    const request = jest.fn(async (path: string) => {
      if (path === "/timeline/41") return event;
      return { items: [event], total: 1 };
    });
    let testRenderer!: ReactTestRenderer;
    await act(async () => { testRenderer = renderer.create(<TimelineScreen request={request} />); });
    const tree: ReactTestInstance = testRenderer.root;
    expect(JSON.stringify(testRenderer.toJSON())).toContain("Laboratory test scheduled");
    const testsFilter = tree.findAllByType(Pressable).find((button) => button.findAllByType(Text).some((text) => text.props.children === "Laboratory tests"));
    await act(async () => { testsFilter?.props.onPress(); });
    expect(request).toHaveBeenLastCalledWith(expect.stringContaining("event_type=test_recommended"));
    const eventButton = tree.findAllByType(Pressable).find((button) => String(button.props.accessibilityLabel ?? "").startsWith("Laboratory test scheduled"));
    await act(async () => { await eventButton?.props.onPress(); });
    expect(request).toHaveBeenLastCalledWith("/timeline/41");
    expect(JSON.stringify(testRenderer.toJSON())).toContain("Event details");
    testRenderer.unmount();
  });

  it("shows next steps only from supplied verified timeline summary entries", async () => {
    const onOpen = jest.fn();
    let testRenderer!: ReactTestRenderer;
    await act(async () => { testRenderer = renderer.create(<NextStepsCard steps={[{ event_id: 41, event_type: "test_scheduled", title: event.title, description: event.description, event_date: event.event_date, action: "Complete your scheduled laboratory test.", status: "scheduled" }]} loading={false} onOpenTimeline={onOpen} />); });
    const tree = testRenderer.root;
    expect(JSON.stringify(testRenderer.toJSON())).toContain("Complete your scheduled laboratory test.");
    const button = tree.findAllByType(Pressable).find((item) => item.findAllByType(Text).some((text) => text.props.children === "Open healthcare timeline  ›"));
    await act(async () => { button?.props.onPress(); });
    expect(onOpen).toHaveBeenCalledTimes(1);
    testRenderer.unmount();
  });
});
