import type { SVGProps } from 'react';

type IconProps = SVGProps<SVGSVGElement>;

function Icon({ children, ...props }: IconProps) {
  return (
    <svg
      width="18"
      height="18"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...props}
    >
      {children}
    </svg>
  );
}

export const PlusIcon = (p: IconProps) => <Icon {...p}><path d="M12 5v14M5 12h14" /></Icon>;
export const MinusIcon = (p: IconProps) => <Icon {...p}><path d="M5 12h14" /></Icon>;
export const UploadIcon = (p: IconProps) => (
  <Icon {...p}><path d="M7 18a4.5 4.5 0 0 1-.9-8.9A6 6 0 0 1 17.7 8 4 4 0 0 1 17 18" /><path d="M12 12v9M8.5 15.5 12 12l3.5 3.5" /></Icon>
);
export const ImageIcon = (p: IconProps) => (
  <Icon {...p}><rect x="3" y="4" width="18" height="16" rx="3" /><circle cx="9" cy="10" r="1.6" /><path d="m21 16-5-5-8 9" /></Icon>
);
export const VideoIcon = (p: IconProps) => (
  <Icon {...p}><rect x="3" y="5" width="14" height="14" rx="3" /><path d="m17 10 4-2.5v9L17 14" /></Icon>
);
export const NoteIcon = (p: IconProps) => (
  <Icon {...p}><path d="M5 4h14v11l-5 5H5z" /><path d="M14 20v-5h5M9 9h6M9 13h3" /></Icon>
);
export const PointerIcon = (p: IconProps) => (
  <Icon {...p}><path d="m5 3 14 7-6 2-2 6z" /></Icon>
);
export const HandIcon = (p: IconProps) => (
  <Icon {...p}><path d="M8 13V5.5a1.5 1.5 0 0 1 3 0V12M11 5a1.5 1.5 0 0 1 3 0v7M14 6.5a1.5 1.5 0 0 1 3 0V13M17 9.5a1.5 1.5 0 0 1 3 0V15a6 6 0 0 1-6 6h-1.5a6 6 0 0 1-4.8-2.4L4.5 15.4a1.6 1.6 0 0 1 2.4-2.1L8 14.5" /></Icon>
);
export const EdgesIcon = (p: IconProps) => (
  <Icon {...p}><circle cx="5" cy="6" r="2" /><circle cx="19" cy="18" r="2" /><path d="M7 6h4a2 2 0 0 1 2 2v8a2 2 0 0 0 2 2h2" /></Icon>
);
export const EdgesOffIcon = (p: IconProps) => (
  <Icon {...p}><circle cx="5" cy="6" r="2" /><circle cx="19" cy="18" r="2" /><path d="M7 6h4a2 2 0 0 1 2 2v8a2 2 0 0 0 2 2h2" opacity="0.35" /><path d="m4 20 16-16" /></Icon>
);
export const SunIcon = (p: IconProps) => (
  <Icon {...p}><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></Icon>
);
export const MoonIcon = (p: IconProps) => (
  <Icon {...p}><path d="M20 14.5A8 8 0 1 1 9.5 4 6.5 6.5 0 0 0 20 14.5z" /></Icon>
);
export const MoreIcon = (p: IconProps) => (
  <Icon {...p}><circle cx="5" cy="12" r="1.3" fill="currentColor" /><circle cx="12" cy="12" r="1.3" fill="currentColor" /><circle cx="19" cy="12" r="1.3" fill="currentColor" /></Icon>
);
export const DownloadIcon = (p: IconProps) => (
  <Icon {...p}><path d="M12 4v11M7.5 10.5 12 15l4.5-4.5" /><path d="M5 19h14" /></Icon>
);
export const ExpandIcon = (p: IconProps) => (
  <Icon {...p}><path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5" /></Icon>
);
export const DuplicateIcon = (p: IconProps) => (
  <Icon {...p}><rect x="8" y="8" width="12" height="12" rx="2.5" /><path d="M16 8V6.5A2.5 2.5 0 0 0 13.5 4h-7A2.5 2.5 0 0 0 4 6.5v7A2.5 2.5 0 0 0 6.5 16H8" /></Icon>
);
export const CloseIcon = (p: IconProps) => <Icon {...p}><path d="M6 6l12 12M18 6 6 18" /></Icon>;
export const PlayIcon = (p: IconProps) => (
  <Icon {...p}><path d="M8 5.5v13l10.5-6.5z" fill="currentColor" /></Icon>
);
export const PauseIcon = (p: IconProps) => (
  <Icon {...p}><path d="M8 5v14M16 5v14" strokeWidth="3" /></Icon>
);
export const VolumeIcon = (p: IconProps) => (
  <Icon {...p}><path d="M4 9.5h3.5L12 5.5v13l-4.5-4H4z" /><path d="M15.5 9a4 4 0 0 1 0 6M18 6.5a7.5 7.5 0 0 1 0 11" /></Icon>
);
export const MuteIcon = (p: IconProps) => (
  <Icon {...p}><path d="M4 9.5h3.5L12 5.5v13l-4.5-4H4z" /><path d="m16 9.5 5 5M21 9.5l-5 5" /></Icon>
);
export const ChevronLeftIcon = (p: IconProps) => <Icon {...p}><path d="m14.5 6-6 6 6 6" /></Icon>;
export const ChevronRightIcon = (p: IconProps) => <Icon {...p}><path d="m9.5 6 6 6-6 6" /></Icon>;
export const SparkIcon = (p: IconProps) => (
  <Icon {...p}><path d="M12 3.5 13.8 9a2 2 0 0 0 1.2 1.2l5.5 1.8-5.5 1.8a2 2 0 0 0-1.2 1.2L12 20.5 10.2 15a2 2 0 0 0-1.2-1.2L3.5 12 9 10.2A2 2 0 0 0 10.2 9z" /></Icon>
);
export const SendIcon = (p: IconProps) => <Icon {...p}><path d="M12 19V5M6 11l6-6 6 6" /></Icon>;
export const StopIcon = (p: IconProps) => <Icon {...p}><rect x="6.5" y="6.5" width="11" height="11" rx="2" fill="currentColor" /></Icon>;
export const UndoIcon = (p: IconProps) => <Icon {...p}><path d="M9 14 4 9l5-5" /><path d="M4 9h10.5a5.5 5.5 0 0 1 0 11H11" /></Icon>;
export const CopyIcon = (p: IconProps) => (
  <Icon {...p}><rect x="8" y="8" width="12" height="12" rx="2.5" /><path d="M16 8V6.5A2.5 2.5 0 0 0 13.5 4h-7A2.5 2.5 0 0 0 4 6.5v7A2.5 2.5 0 0 0 6.5 16H8" /></Icon>
);
export const CheckIcon = (p: IconProps) => <Icon {...p}><path d="m5 12.5 4.5 4.5L19 7.5" /></Icon>;
export const NoteAddIcon = (p: IconProps) => (
  <Icon {...p}><path d="M5 4h14v11l-5 5H5z" /><path d="M14 20v-5h5M12 8v6M9 11h6" /></Icon>
);
