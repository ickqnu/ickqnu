import { useState } from 'react'

const LINKS = ['Labs', 'Studio', 'Openings', 'Shop']

export default function Navbar() {
  const [menuOpen, setMenuOpen] = useState(false)

  return (
    <>
      <header className="fixed top-0 left-0 z-10 flex w-full items-center justify-between px-5 py-4 sm:px-8 sm:py-5">
        <div className="flex items-center gap-3">
          <span
            className="text-[21px] tracking-tight text-black sm:text-[26px]"
            style={{ fontFamily: 'var(--font-heading)' }}
          >
            Hamco&reg;
          </span>
          <span
            className="text-[25px] text-black select-none sm:text-[30px]"
            style={{ letterSpacing: '-0.02em' }}
          >
            ✳︎
          </span>
        </div>

        <nav className="hidden text-[23px] text-black md:flex">
          {LINKS.map((link, i) => (
            <span key={link}>
              <a href="#" className="transition-opacity hover:opacity-60">
                {link}
              </a>
              {i < LINKS.length - 1 && <span>,&nbsp;</span>}
            </span>
          ))}
        </nav>

        <a
          href="#"
          className="hidden text-[23px] text-black underline underline-offset-2 transition-opacity hover:opacity-60 md:block"
        >
          Get in touch
        </a>

        <button
          type="button"
          aria-label="Toggle menu"
          onClick={() => setMenuOpen((open) => !open)}
          className="flex flex-col gap-[5px] md:hidden"
        >
          <span
            className={`h-[2px] w-6 bg-black transition-transform duration-300 ${
              menuOpen ? 'translate-y-[7px] rotate-45' : ''
            }`}
          />
          <span
            className={`h-[2px] w-6 bg-black transition-opacity duration-300 ${
              menuOpen ? 'opacity-0' : ''
            }`}
          />
          <span
            className={`h-[2px] w-6 bg-black transition-transform duration-300 ${
              menuOpen ? '-translate-y-[7px] -rotate-45' : ''
            }`}
          />
        </button>
      </header>

      <div
        className={`fixed inset-0 z-[9] flex flex-col justify-center gap-8 bg-white/95 px-8 backdrop-blur-sm transition-opacity duration-300 md:hidden ${
          menuOpen ? 'opacity-100' : 'pointer-events-none opacity-0'
        }`}
      >
        {LINKS.map((link) => (
          <a
            key={link}
            href="#"
            className="text-[32px] font-medium text-black"
            onClick={() => setMenuOpen(false)}
          >
            {link}
          </a>
        ))}
        <a
          href="#"
          className="text-[32px] font-medium text-black underline underline-offset-2"
          onClick={() => setMenuOpen(false)}
        >
          Get in touch
        </a>
      </div>
    </>
  )
}
