type Name = "grid" | "cpu" | "queue" | "key" | "code" | "arrow" | "logout" | "plus" | "refresh" | "download" | "check" | "close" | "pulse" | "sun";
const paths: Record<Name, React.ReactNode> = {
  grid: <><rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/></>,
  cpu: <><rect x="5" y="5" width="14" height="14" rx="3"/><rect x="9" y="9" width="6" height="6" rx="1"/><path d="M9 2v3m6-3v3M9 19v3m6-3v3M2 9h3m-3 6h3m14-6h3m-3 6h3"/></>,
  queue: <><path d="M8 6h13M8 12h13M8 18h13"/><circle cx="3" cy="6" r="1"/><circle cx="3" cy="12" r="1"/><circle cx="3" cy="18" r="1"/></>,
  key: <><circle cx="8" cy="8" r="5"/><path d="m12 12 9 9m-3-3 3-3m-6 0 3-3"/></>,
  code: <path d="m8 5-6 7 6 7m8-14 6 7-6 7m-3-16-2 18"/>,
  arrow: <path d="M5 12h14m-5-5 5 5-5 5"/>, logout: <path d="M9 4H4v16h5m5-12 4 4-4 4M8 12h13"/>,
  plus: <path d="M12 5v14M5 12h14"/>, refresh: <><path d="M20 11a8 8 0 1 0-2 6M20 4v7h-7"/></>,
  download: <path d="M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5"/>, check: <path d="m5 12 4 4L20 5"/>,
  close: <path d="m6 6 12 12M6 18 18 6"/>, pulse: <path d="M2 12h5l3-8 4 16 3-8h5"/>,
  sun: <><circle cx="12" cy="12" r="4"/><path d="M12 1v3m0 16v3M1 12h3m16 0h3M4 4l2 2m12 12 2 2M4 20l2-2M18 6l2-2"/></>,
};
export function Icon({ name, size = 20 }: { name: Name; size?: number }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>;
}
