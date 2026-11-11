import { render } from "@testing-library/react";
import { RegionLabel } from "../RegionLabel";

const configuredLabel = (value: string, display: string, alias?: string) => ({
  id: value,
  value,
  _value: value,
  html: display,
  alias,
  background: "#123456",
});

const regionWithLabels = (...labels: any[]) => ({
  type: "rectangleregion",
  labelings: [
    {
      mainValue: labels.map((label) => label.resultValue ?? label.value),
      from_name: { findLabel: (value: string) => labels.find((label) => label.resultValue === value) },
      selectedLabels: labels,
    },
  ],
});

describe("Regions label display", () => {
  it.each([
    ["scratch", "划痕", "划痕"],
    ["outer_shell", "<b>外壳轮廓</b>", "外壳轮廓"],
    ["scratch", "", "scratch"],
  ])("uses the configured display text and falls back to the value", (value, html, expected) => {
    const { container } = render(<RegionLabel item={{ type: "rectanglelabels", value, html, _value: value }} />);

    expect(container.textContent).toBe(expected);
  });

  it("resolves aliases and html display text for regions", () => {
    const label = configuredLabel("划痕", "划痕", "scratch");
    const resultLabel = { ...label, resultValue: "scratch" };
    const { container } = render(<RegionLabel item={regionWithLabels(resultLabel)} />);

    expect(container.textContent).toBe("划痕");
  });

  it("keeps the original result value when the configuration has no mapping", () => {
    const { container } = render(
      <RegionLabel
        item={{
          ...regionWithLabels(),
          labelings: [{ mainValue: ["unknown_defect"], from_name: { findLabel: () => undefined } }],
        }}
      />,
    );

    expect(container.textContent).toBe("unknown_defect");
  });

  it("shows No label for an empty configured label", () => {
    const emptyLabel = { id: "empty", value: null, _value: "blank", html: "", background: "#666", isEmpty: true };
    const { container } = render(
      <RegionLabel
        item={{
          type: "rectangleregion",
          labelings: [{ mainValue: [], from_name: { findLabel: () => emptyLabel }, selectedLabels: [emptyLabel] }],
        }}
      />,
    );

    expect(container.textContent).toBe("No label");
  });
});
