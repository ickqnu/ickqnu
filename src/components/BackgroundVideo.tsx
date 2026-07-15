import { useEffect, useRef } from 'react'

const VIDEO_SRC =
  'https://d8j0ntlcm91z4.cloudfront.net/user_38xzZboKViGWJOttwIXH07lWA1P/hf_20260530_042513_df96a13b-6155-4f6e-8b93-c9dee66fba08.mp4'

const SENSITIVITY = 0.8

export default function BackgroundVideo() {
  const videoRef = useRef<HTMLVideoElement>(null)
  const prevX = useRef<number | null>(null)
  const targetTime = useRef(0)
  const requestedTime = useRef<number | null>(null)

  useEffect(() => {
    const video = videoRef.current
    if (!video) return

    const seekTo = (time: number) => {
      requestedTime.current = time
      video.currentTime = time
    }

    const onSeeked = () => {
      // Queue the next seek only if the target moved while we were seeking.
      if (targetTime.current !== requestedTime.current) {
        seekTo(targetTime.current)
      } else {
        requestedTime.current = null
      }
    }

    const onMouseMove = (e: MouseEvent) => {
      if (prevX.current === null) {
        prevX.current = e.clientX
        return
      }
      const delta = e.clientX - prevX.current
      prevX.current = e.clientX

      const duration = video.duration
      if (!duration || Number.isNaN(duration)) return

      const offset = (delta / window.innerWidth) * SENSITIVITY * duration
      targetTime.current = Math.min(
        Math.max(targetTime.current + offset, 0),
        duration,
      )

      if (requestedTime.current === null) {
        seekTo(targetTime.current)
      }
    }

    video.addEventListener('seeked', onSeeked)
    window.addEventListener('mousemove', onMouseMove)
    return () => {
      video.removeEventListener('seeked', onSeeked)
      window.removeEventListener('mousemove', onMouseMove)
    }
  }, [])

  return (
    <video
      ref={videoRef}
      src={VIDEO_SRC}
      muted
      playsInline
      preload="auto"
      className="fixed inset-0 z-0 h-full w-full object-cover"
      style={{ objectPosition: '70% center' }}
    />
  )
}
