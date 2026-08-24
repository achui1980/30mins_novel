import { useState } from "react";
import TimelineTab from "../tabs/TimelineTab";
import StackShell from "./StackShell";

export default function TimelineStack({ id, onBack, onViewChapter }) {
  const [right, setRight] = useState(null);
  return (
    <StackShell title="完整时间轴" onBack={onBack} right={right}>
      <div className="px-6 py-4">
        <TimelineTab id={id} setRight={setRight} onViewChapter={onViewChapter} />
      </div>
    </StackShell>
  );
}
