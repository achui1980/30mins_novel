import { useState } from "react";
import GraphTab from "../tabs/GraphTab";
import StackShell from "./StackShell";

export default function GraphStack({ id, onBack, onViewChapter }) {
  const [right, setRight] = useState(null);
  return (
    <StackShell title="完整人物关系图谱" onBack={onBack} right={right}>
      <div className="px-6 py-4">
        <GraphTab id={id} setRight={setRight} onViewChapter={onViewChapter} />
      </div>
    </StackShell>
  );
}
