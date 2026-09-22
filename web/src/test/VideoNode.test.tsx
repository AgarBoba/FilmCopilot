import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { ImageNode } from '../nodes/ImageNode';
import { VideoNode } from '../nodes/VideoNode';


describe('media nodes', () => {
  it('plays only while the video node is hovered', async () => {
    const play = vi.fn().mockResolvedValue(undefined);
    const pause = vi.fn();
    render(<VideoNode data={{ assetUrl: '/video.mp4', play, pause }} />);
    await userEvent.hover(screen.getByTestId('video-node'));
    expect(play).toHaveBeenCalledOnce();
    await userEvent.unhover(screen.getByTestId('video-node'));
    expect(pause).toHaveBeenCalledOnce();
  });

  it('renders image thumbnails from direct upstream references', () => {
    render(
      <ImageNode
        data={{ assetUrl: '/main.png', references: ['/ref-a.png', '/ref-b.png'] }}
      />,
    );
    expect(screen.getByAltText('reference-1')).toBeInTheDocument();
    expect(screen.getByAltText('reference-2')).toBeInTheDocument();
  });
});
