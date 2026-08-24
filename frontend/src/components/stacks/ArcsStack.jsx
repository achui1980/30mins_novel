import { useState } from "react";
import ArcsTab from "../tabs/ArcsTab";
import StackShell from "./StackShell";

export default function ArcsStack({ id, ls, onBack }) {
  const [right, setRight] = useState(null);
  return (
    <StackShell title="完整情节脉络" onBack={onBack} right={right}>
      <div className="px-6 py-4">
        <ArcsTab id={id} ls={ls} setRight={setRight} />
      </div>
    </StackShell>
  );
}
