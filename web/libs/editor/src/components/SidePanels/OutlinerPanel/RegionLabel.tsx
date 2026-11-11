import { observer } from "mobx-react";
import { memo } from "react";
import { cn } from "../../../utils/bem";

export type RegionLabelProps = {
  item: any;
};

function labelDisplayName(label: any) {
  if (label.value == null || label.isEmpty) return undefined;
  if (label.html) {
    const template = document.createElement("template");
    template.innerHTML = label.html;
    const text = template.content.textContent?.trim();
    if (text) return text;
  }
  return label._value || label.value;
}

const ClassificationLabel = observer(({ item }: { item: any }) => {
  const results = item.results ?? [];

  if (!results.length) return "Classification";

  return (
    <div className={cn("labels-list").toClassName()}>
      {results.map((result: any, rIdx: number) => {
        const values = result.mainValue;

        if (!values || !Array.isArray(values) || values.length === 0) {
          return <span key={result.id}>{result.from_name?.name ?? "Classification"}</span>;
        }
        return values.map((val: any, vIdx: number) => {
          const display = Array.isArray(val) ? val.join(" > ") : String(val);

          return [rIdx > 0 || vIdx > 0 ? ", " : null, <span key={`${result.id}-${vIdx}`}>{display}</span>];
        });
      })}
    </div>
  );
});

export const RegionLabel = memo(
  observer(({ item }: RegionLabelProps) => {
    const { type } = item ?? {};
    if (item?.classification) {
      return <ClassificationLabel item={item} />;
    }
    if (!type) {
      return "No Label";
    }
    if (type.includes("label")) {
      return labelDisplayName(item);
    }
    if (type === "reactcode") {
      if (item.values?.length) {
        return (
          <div className={cn("labels-list").toClassName()}>
            {item.values.map((value: string, index: number) => [
              index ? ", " : null,
              <div key={value} className={cn("labels-list").toClassName()}>
                {value.length > 50 ? `${value.slice(0, 50)}...` : value}
              </div>,
            ])}
          </div>
        );
      }
    }
    if (type.includes("region") || type.includes("range")) {
      const labelsInResults = item.labelings.map((result: any) =>
        result.mainValue?.length
          ? result.mainValue.map(
              (value: any) =>
                result.from_name.findLabel(value) ?? { value: Array.isArray(value) ? value.join(" > ") : value },
            )
          : result.selectedLabels || [],
      );

      const labels: any[] = [].concat(...labelsInResults);

      return (
        <div className={cn("labels-list").toClassName()}>
          {labels.map((label, index) => {
            const color = label.background || "#000000";

            return [
              index ? ", " : null,
              // This comes from an Elem tag that was set without a name. The CSS was fixed to make it work,
              // but this is clearly bad CSS usage.
              <div key={label.id ?? index} className={cn("labels-list").toClassName()} style={{ color }}>
                {labelDisplayName(label) || "No label"}
              </div>,
            ];
          })}
        </div>
      );
    }
    if (type.includes("tool")) {
      return item.value;
    }
  }),
  (prevProps, nextProps) => {
    if (prevProps.item !== nextProps.item) return false;
    if (prevProps.item?.highlighted !== nextProps.item?.highlighted) return false;
    if (prevProps.item?.hidden !== nextProps.item?.hidden) return false;
    return true;
  },
);
