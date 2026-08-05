import { useCallback, useEffect, useState } from "react";
import { listWorks } from "../api";

export function useWorksList() {
  const [works, setWorks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const refresh = useCallback(() => {
    setLoading(true);
    listWorks()
      .then((data) => {
        setWorks(data);
        setError("");
      })
      .catch((e) => setError(e.message || "加载失败"))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return { works, loading, error, refresh };
}
