import { useEffect, useState } from 'react';
import type { MutableRefObject, RefObject } from 'react';

import { MuteIcon, PauseIcon, PlayIcon, VolumeIcon } from '../canvas/icons';


interface VideoPlayerProps {
  src: string;
  poster?: string;
  videoRef: RefObject<HTMLVideoElement | null>;
  /** Set to true once the user uses the controls, so hover preview stops taking over. */
  manualRef: MutableRefObject<boolean>;
}

function formatTime(seconds: number) {
  if (!Number.isFinite(seconds) || seconds < 0) return '0:00';
  const whole = Math.floor(seconds);
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, '0')}`;
}


/**
 * Video with a compact control bar: play/pause, progress (drag to seek), time, sound.
 * Hovering the node still plays a silent preview (see VideoNode); once the user
 * touches the controls, playback is theirs until the pointer leaves a paused video.
 */
export function VideoPlayer({ src, poster, videoRef, manualRef }: VideoPlayerProps) {
  const [playing, setPlaying] = useState(false);
  const [current, setCurrent] = useState(0);
  const [duration, setDuration] = useState(0);
  const [muted, setMuted] = useState(true);

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return undefined;
    const sync = () => {
      setPlaying(!video.paused && !video.ended);
      setCurrent(video.currentTime);
      setDuration(Number.isFinite(video.duration) ? video.duration : 0);
      setMuted(video.muted);
    };
    const events = ['play', 'pause', 'ended', 'timeupdate', 'loadedmetadata', 'durationchange', 'volumechange', 'seeked'];
    events.forEach((name) => video.addEventListener(name, sync));
    sync();
    return () => events.forEach((name) => video.removeEventListener(name, sync));
  }, [videoRef, src]);

  function togglePlay() {
    const video = videoRef.current;
    if (!video) return;
    manualRef.current = true;
    if (video.paused || video.ended) {
      if (video.ended) video.currentTime = 0;
      void video.play().catch(() => undefined);
    } else {
      video.pause();
    }
  }

  function toggleMute() {
    const video = videoRef.current;
    if (!video) return;
    video.muted = !video.muted;
  }

  function seek(value: number) {
    const video = videoRef.current;
    if (!video) return;
    manualRef.current = true;
    video.currentTime = value;
    setCurrent(value);
  }

  const progress = duration ? (current / duration) * 100 : 0;

  return (
    <div className={`video-player ${playing ? 'is-playing' : 'is-paused'}`}>
      <video
        ref={videoRef}
        src={src}
        poster={poster}
        muted
        playsInline
        preload="metadata"
        onClick={(event) => {
          event.stopPropagation();
          togglePlay();
        }}
      />
      <div className="video-controls nodrag nopan nowheel" onPointerDown={(event) => event.stopPropagation()}>
        <button
          type="button"
          aria-label={playing ? '暂停' : '播放'}
          data-tooltip={playing ? '暂停' : '播放'}
          onClick={(event) => {
            event.stopPropagation();
            togglePlay();
          }}
        >
          {playing ? <PauseIcon width={14} height={14} /> : <PlayIcon width={14} height={14} />}
        </button>
        <input
          type="range"
          className="video-progress"
          aria-label="播放进度"
          min={0}
          max={duration || 0}
          step={0.01}
          value={Math.min(current, duration || 0)}
          style={{ '--progress': `${progress}%` } as React.CSSProperties}
          onChange={(event) => seek(Number(event.target.value))}
          onClick={(event) => event.stopPropagation()}
        />
        <span className="video-time" aria-label="播放时间">
          {formatTime(current)} / {formatTime(duration)}
        </span>
        <button
          type="button"
          aria-label={muted ? '打开声音' : '静音'}
          data-tooltip={muted ? '打开声音' : '静音'}
          onClick={(event) => {
            event.stopPropagation();
            toggleMute();
          }}
        >
          {muted ? <MuteIcon width={14} height={14} /> : <VolumeIcon width={14} height={14} />}
        </button>
      </div>
    </div>
  );
}
