import asyncio
import json
import random
import argparse
from enum import Enum, auto
from dataclasses import dataclass, field
from typing import Optional
from pathlib import Path
import pygame

# Use pygame to play earcons
pygame.mixer.init()

class Role(Enum):
    TOWNFOLK = "townfolk"
    MAFIA = "mafia"
    DOCTOR = "doctor"
    DETECTIVE = "detective"

class Phase(Enum):
    DAY = auto()
    NIGHT_MAFIA = auto()
    NIGHT_DOCTOR = auto()
    NIGHT_DETECTIVE = auto()

@dataclass
class Player:
    id: int
    role: Role
    alive: bool = True

@dataclass
class GameState:
    players: dict = field(default_factory=dict)
    phase: Phase = Phase.DAY
    pending_kill_id: Optional[int] = None
    pending_save_id: Optional[int] = None

# Handle earcons
class SoundManager:
    SOUND_FILES = {
        "wake": "wakeUpSound",
        "sleep": "gotoSleepSound",
        "everyone": "everyoneSound",
        "mafia": "mafiaSound",
        "doctor": "doctorSound",
        "detective": "detectiveSound",
        "lynch": "lynchSound",
        "protection": "protectSound",
        "hint": "checkSound",
    }

    def __init__(self, sound_dir: str = "./earcons", enabled: bool = True):
        self.sound_dir = Path(sound_dir).resolve()
        self.enabled = enabled
        self._sounds_cache = {}
        
        if self.enabled:
            # Initialize mixer with specific settings for better compatibility
            pygame.mixer.quit()
            pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
            self._preload_sounds()

    def _preload_sounds(self) -> None:
        print(f"Loading sounds from: {self.sound_dir}")
        for key, filename in self.SOUND_FILES.items():
            path = self.sound_dir / f"{filename}.mp3"
            if path.exists():
                try:
                    self._sounds_cache[key] = pygame.mixer.Sound(str(path))
                except Exception as e:
                    print(f"Failed to load {filename}.mp3: {e}")
            else:
                print(f"Not found: {path}")

    def play(self, sound_key: str) -> None:
        if not self.enabled:
            return

        sound = self._sounds_cache.get(sound_key)
        if sound is None:
            print(f"  [Sound not loaded: {sound_key}]")
            return

        try:
            channel = sound.play()
            if channel:
                while channel.get_busy():
                    pygame.time.wait(50)
        except Exception as e:
            print(f"  [Sound error: {e}]")

    def play_sequence(self, *sound_keys: str) -> None:
        for key in sound_keys:
            self.play(key)

# Sends tap commands to the broker for the wristbands
class TapManager:
    ROLE_TAPS = {
        Role.TOWNFOLK: 1,
        Role.MAFIA: 2,
        Role.DOCTOR: 3,
        Role.DETECTIVE: 4,
    }

    def __init__(self, writer, topic: str, enabled: bool = True):
        self.writer = writer
        self.topic = topic
        self.enabled = enabled

    # Send taps to some wristband
    async def send(self, player_id: int, taps: int) -> None:
        if not self.enabled:
            return

        payload = json.dumps({"id": player_id, "taps": taps})
        message = json.dumps({
            "type": "publish",
            "topic": self.topic,
            "payload": payload
        })
        self.writer.write(message.encode())
        await self.writer.drain()
        print(f"Sent {taps} tap(s) to wristband {player_id}")

    # For communicating with some role
    async def send_to_role(self, players: dict, role: Role, taps: int) -> None:
        for player in players.values():
            if player.alive and player.role == role:
                await self.send(player.id, taps)

    # All alive players
    async def send_to_all_alive(self, players: dict, taps: int) -> None:
        for player in players.values():
            if player.alive:
                await self.send(player.id, taps)
                await asyncio.sleep(0.1)

    # Initial role distribution taps
    async def distribute_roles(self, players: dict) -> None:
        print("\nDistributing roles via taps...")
        for player in players.values():
            taps = self.ROLE_TAPS[player.role]
            await self.send(player.id, taps)
            await asyncio.sleep(0.8)

# Game controller
class MafiaGame:
    PLAYER_COUNT = 4
    TOPIC = "mafia"

    def __init__(self, host: str, port: int, only_sound: bool, only_taps: bool):
        self.host = host
        self.port = port
        self.only_sound = only_sound
        self.only_taps = only_taps

        self.state = GameState()
        self.sound: Optional[SoundManager] = None
        self.taps: Optional[TapManager] = None
        self.writer = None
        self.reader = None

    # Randomize wristband roles
    def _initialize_players(self) -> None:
        roles = [Role.MAFIA, Role.DOCTOR, Role.DETECTIVE, Role.TOWNFOLK]
        random.shuffle(roles)

        self.state.players = {
            i: Player(id=i, role=roles[i - 1])
            for i in range(1, self.PLAYER_COUNT + 1)
        }
        self.state.phase = Phase.DAY
        
        # Potential actions
        self.state.pending_kill_id = None
        self.state.pending_save_id = None

        # Print player roles
        for player in self.state.players.values():
            print(f"Wristband {player.id}: {player.role.value.upper()}")
        print("=" * 40 + "\n")

    # Connect game object to MQTT broker
    async def _connect(self) -> None:
        self.reader, self.writer = await asyncio.open_connection(
            self.host, self.port
        )

        subscribe_msg = json.dumps({
            "type": "subscribe",
            "topic": self.TOPIC
        })
        self.writer.write(subscribe_msg.encode())
        await self.writer.drain()

        taps_enabled = not self.only_sound
        sound_enabled = not self.only_taps

        self.sound = SoundManager(enabled=sound_enabled)
        self.taps = TapManager(self.writer, self.TOPIC, enabled=taps_enabled)

        print(f"Connected to broker at {self.host}:{self.port}")

    # Returns player id
    def _get_player(self, player_id: int) -> Optional[Player]:
        return self.state.players.get(player_id)

    # Returns player alive status
    def _get_alive_player(self, player_id: int) -> Optional[Player]:
        """Get an alive player by ID."""
        player = self._get_player(player_id)
        return player if player and player.alive else None

    # Returns the alive status of a role
    def _is_role_alive(self, role: Role) -> bool:
        return any(p.alive and p.role == role for p in self.state.players.values())

    # Phases
    async def _wake_everyone(self) -> None:
        """Day phase - wake up all alive players."""
        self.state.phase = Phase.DAY
        print("\nDaytime")

        self.sound.play_sequence("wake", "everyone")
        await self.taps.send_to_all_alive(self.state.players, 2)

    async def _start_night(self) -> None:
        """Begin night phase - everyone sleeps, then mafia wakes."""
        self.state.pending_kill_id = None
        self.state.pending_save_id = None

        print("\nNight phase")
        self.sound.play_sequence("sleep", "everyone")
        await self.taps.send_to_all_alive(self.state.players, 2)

        await asyncio.sleep(0.5)
        await self._wake_mafia()

    # Awaken roles one by one
    async def _wake_mafia(self) -> None:
        self.state.phase = Phase.NIGHT_MAFIA
        print("\nMafia wakes up")
        self.sound.play_sequence("wake", "mafia")
        await self.taps.send_to_role(self.state.players, Role.MAFIA, 2)

    async def _sleep_and_wake_doctor(self) -> None:
        if self._is_role_alive(Role.MAFIA):
            print("Mafia goes to sleep")
            self.sound.play_sequence("sleep", "mafia")
            await asyncio.sleep(0.3)

        self.state.phase = Phase.NIGHT_DOCTOR

        if not self._is_role_alive(Role.DOCTOR):
            print("Doctor is dead. Skip.")
            await self._sleep_and_wake_detective()
            return

        print("\nDoctor wakes up.")
        self.sound.play_sequence("wake", "doctor")
        await self.taps.send_to_role(self.state.players, Role.DOCTOR, 2)

        print("Use 'save X' to protect someone, then 'next'.")

    async def _sleep_and_wake_detective(self) -> None:
        if self._is_role_alive(Role.DOCTOR):
            print("\nDoctor goes to sleep.")
            self.sound.play_sequence("sleep", "doctor")
            await asyncio.sleep(0.3)

        self.state.phase = Phase.NIGHT_DETECTIVE

        if not self._is_role_alive(Role.DETECTIVE):
            print("Detective is dead. Skip")
            await self._end_night()
            return

        print("\nDetective wakes up.")
        self.sound.play_sequence("wake", "detective")
        await self.taps.send_to_role(self.state.players, Role.DETECTIVE, 2)

    async def _end_night(self) -> None:
        if self._is_role_alive(Role.DETECTIVE):
            print("\nDetective goes to sleep.")
            self.sound.play_sequence("sleep", "detective")
            await asyncio.sleep(0.3)

        # Resolve kill/save
        if self.state.pending_kill_id is not None:
            victim = self._get_player(self.state.pending_kill_id)

            if victim and victim.alive:
                if self.state.pending_save_id == self.state.pending_kill_id:
                    print(f"\nPlayer {victim.id} was saved by the doctor.")
                    self.sound.play("protection")
                else:
                    victim.alive = False
                    print(f"\nPlayer {victim.id} ({victim.role.value}) was killed.")
                    self.sound.play_sequence("lynch", "everyone")
                    await self.taps.send(victim.id, 1)

        self.state.pending_kill_id = None
        self.state.pending_save_id = None

        await asyncio.sleep(0.5)
        await self._wake_everyone()
        self._check_win_condition()

    # Progress the game
    async def next_phase(self) -> None:
        phase = self.state.phase

        if phase == Phase.DAY:
            await self._start_night()
        elif phase == Phase.NIGHT_MAFIA:
            await self._sleep_and_wake_doctor()
        elif phase == Phase.NIGHT_DOCTOR:
            await self._sleep_and_wake_detective()
        elif phase == Phase.NIGHT_DETECTIVE:
            await self._end_night()

    # Player actions
    async def kill_player(self, player_id: int) -> None:
        target = self._get_alive_player(player_id)
        if target is None:
            print(f"Player {player_id} is not a valid target.")
            return

        if self.state.phase == Phase.DAY:
            await self._lynch(target)
        elif self.state.phase == Phase.NIGHT_MAFIA:
            self.state.pending_kill_id = player_id
            print(f"Mafia targets player {player_id}.")
            # Send sleep taps to mafia
            await self.taps.send_to_role(self.state.players, Role.MAFIA, 2)
            # Advance to doctor
            await self.next_phase()

    async def _lynch(self, target: Player) -> None:
        target.alive = False
        print(f"\nPlayer {target.id} has been lynched.")

        self.sound.play("lynch")

        if target.role == Role.MAFIA:
            print(f"They were the mafia!")
            self.sound.play("mafia")
        else:
            print(f"   They were the {target.role.value}.")
            self.sound.play("everyone")

        self._check_win_condition()

    async def save_player(self, player_id: int) -> None:
        if self.state.phase != Phase.NIGHT_DOCTOR:
            print("Saves can only happen during doctor's turn!")
            return

        target = self._get_alive_player(player_id)
        if target is None:
            print(f"Player {player_id} is not a valid target.")
            return

        self.state.pending_save_id = player_id
        print(f"Doctor will protect player {player_id}.")
        # Send sleep taps to doctor
        await self.taps.send_to_role(self.state.players, Role.DOCTOR, 2)
        # Auto-advance to detective
        await self.next_phase()

    async def check_player(self, player_id: int) -> None:
        if self.state.phase != Phase.NIGHT_DETECTIVE:
            print("Checks can only happen during detective's turn!")
            return

        target = self._get_alive_player(player_id)
        if target is None:
            print(f"Player {player_id} is not a valid target.")
            return

        self.sound.play("hint")

        is_mafia = target.role == Role.MAFIA
        result = "Mafia." if is_mafia else f"not mafia ({target.role.value})"
        print(f"Player {player_id} is {result}")
        # Send sleep taps to detective
        await self.taps.send_to_role(self.state.players, Role.DETECTIVE, 2)
        # Auto-advance to end night
        await self.next_phase()

    # Game state
    def _check_win_condition(self) -> None:
        mafia_alive = sum(
            1 for p in self.state.players.values()
            if p.alive and p.role == Role.MAFIA
        )
        town_alive = sum(
            1 for p in self.state.players.values()
            if p.alive and p.role != Role.MAFIA
        )

        if mafia_alive == 0:
            print("\nTOWN WINS! All mafia have been eliminated!")
        elif mafia_alive >= town_alive:
            print("\nMAFIA WINS! They have taken over the town!")

    # Send out taps to wrist bands again
    async def repeat_roles(self, player_id: Optional[int] = None) -> None:
        if player_id is not None:
            player = self._get_player(player_id)
            if player is None:
                print(f"Player {player_id} not found.")
                return
            taps = TapManager.ROLE_TAPS[player.role]
            print(f"Repeating role to player {player_id}...")
            await self.taps.send(player.id, taps)
        else:
            print("Repeating roles to all players...")
            await self.taps.distribute_roles(self.state.players)

    # Switch between game modes
    async def switch_mode(self, mode: str) -> None:
        if mode == "taps":
            self.only_sound = False
            self.only_taps = True
            self.sound.enabled = False
            self.taps.enabled = True
            print("\nSwitched to TAPS ONLY mode.")
        elif mode == "sounds":
            self.only_sound = True
            self.only_taps = False
            self.sound.enabled = True
            self.taps.enabled = False
            print("\nSwitched to SOUNDS ONLY mode.")
        elif mode == "all":
            self.only_sound = False
            self.only_taps = False
            self.sound.enabled = True
            self.taps.enabled = True
            print("\nSwitched to ALL (sounds + taps) mode.")
        
        await self.reset_game()
    async def reset_game(self) -> None:
        print("\nResetting game...")
        self._initialize_players()

        original_taps_enabled = self.taps.enabled
        self.taps.enabled = True
        await self.taps.distribute_roles(self.state.players)
        self.taps.enabled = original_taps_enabled

        print("\nRoles distributed. Type 'next' to start the game.")

    # Game master input
    async def _handle_command(self, command: str) -> bool:
        parts = command.strip().lower().split()

        if not parts:
            return True

        command = parts[0]

        if command == "quit":
            return False
        elif command == "next":
            await self.next_phase()
        elif command == "kill" and len(parts) >= 2:
            try:
                await self.kill_player(int(parts[1]))
            except ValueError:
                print("Usage: kill <player_id>")
        elif command == "save" and len(parts) >= 2:
            try:
                await self.save_player(int(parts[1]))
            except ValueError:
                print("Usage: save <player_id>")
        elif command == "check" and len(parts) >= 2:
            try:
                await self.check_player(int(parts[1]))
            except ValueError:
                print("Usage: check <player_id>")
        elif command == "repeat":
            if len(parts) >= 2:
                try:
                    await self.repeat_roles(int(parts[1]))
                except ValueError:
                    print("Usage: repeat [player_id]")
            else:
                await self.repeat_roles()
        elif command == "reset":
            await self.reset_game()
        elif command == "switch" and len(parts) >= 2:
            await self.switch_mode(parts[1])
        else:
            print(f"Unknown command: {command}. Type 'help' for commands.")

        return True

    # Main loop
    async def run(self) -> None:
        await self._connect()
        self._initialize_players()

        original_taps_enabled = self.taps.enabled
        self.taps.enabled = True
        await self.taps.distribute_roles(self.state.players)
        self.taps.enabled = original_taps_enabled

        print("\nRoles distributed. Type 'next' to start the game.")

        loop = asyncio.get_event_loop()
        running = True

        while running:
            try:
                command = await loop.run_in_executor(None, input, "> ")
                running = await self._handle_command(command)
            except KeyboardInterrupt:
                print("\nExiting...")
                break
            except EOFError:
                break

        if self.writer:
            self.writer.close()
            await self.writer.wait_closed()

        print("Game ended.")


def main():
    # Which version of the game to run
    parser = argparse.ArgumentParser(description="Mafia Game Publisher")
    parser.add_argument("--host", default="192.168.137.1", help="MQTT broker host")
    parser.add_argument("--port", type=int, default=1883, help="MQTT broker port")
    parser.add_argument("--only-sound", action="store_true",
                        help="Taps only for role distribution")
    parser.add_argument("--only-taps", action="store_true", help="No sounds")

    args = parser.parse_args()

    if args.only_sound and args.only_taps:
        print("Error: Cannot use --only-sound and --only-taps together")
        return

    game = MafiaGame(
        host=args.host,
        port=args.port,
        only_sound=args.only_sound,
        only_taps=args.only_taps
    )

    asyncio.run(game.run())


if __name__ == "__main__":
    main()