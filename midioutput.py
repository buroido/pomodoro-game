import pygame.midi
pygame.midi.init()
for i in range(pygame.midi.get_count()):
    interf, name, is_input, is_output, opened = pygame.midi.get_device_info(i)
    if is_output and "loopMIDI Port" in name.decode():
        midi_out = pygame.midi.Output(i)
        print("Opened loopMIDI Port:", name.decode())
        break
else:
    raise RuntimeError("loopMIDI Port が見つかりませんでした。")
