import { useEffect, useState } from "react";
import { api } from "../api/index.js";

export function useApiHealth() {
  const [health, setHealth] = useState({ status: "loading" });

  useEffect(() => {
    let active = true;

    api.getHealth()
      .then((result) => {
        if (active) setHealth(result);
      })
      .catch((error) => {
        if (active) setHealth({ status: "error", message: error.message });
      });

    return () => {
      active = false;
    };
  }, []);

  return health;
}
