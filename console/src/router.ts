import { useEffect, useState } from "react";

export interface Route {
  path: string[];
  params: URLSearchParams;
}

const parse = (): Route => {
  const [path, search] = window.location.hash.replace(/^#\/?/, "").split("?");
  return {
    path: path ? path.split("/").map(decodeURIComponent) : ["overview"],
    params: new URLSearchParams(search ?? ""),
  };
};

export function useRoute() {
  const [route, setRoute] = useState(parse);
  useEffect(() => {
    const update = () => setRoute(parse());
    window.addEventListener("hashchange", update);
    return () => window.removeEventListener("hashchange", update);
  }, []);
  return route;
}

export const href = (...parts: string[]) => `#/${parts.map(encodeURIComponent).join("/")}`;

export const go = (...parts: string[]) => {
  window.location.hash = href(...parts);
};
