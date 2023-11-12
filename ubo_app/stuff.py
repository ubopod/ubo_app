class WifiPrompt(PromptWidget):
    icon = 'wifi_off'
    prompt = 'Not Connected'
    first_option_label = 'Add'
    first_option_icon = 'add'

    def first_option_callback(self: WifiPrompt) -> None:
        notification_manager.notify(
            title='WiFi added',
            content='This WiFi network has been added',
            icon='wifi',
            sender='Wifi',
        )

    second_option_label = 'Forget'
    second_option_icon = 'delete'

    def second_option_callback(self: WifiPrompt) -> None:
        notification_manager.notify(
            title='WiFi forgotten',
            content='This WiFi network is forgotten',
            importance=Importance.CRITICAL,
            sender='WiFi',
        )


    @cached_property
    def cpu_gauge(self: MenuApp) -> GaugeWidget:
        import psutil

        gauge = GaugeWidget(value=0, fill_color='#24D636', label='CPU')

        value = [0]

        def set_value(_: float) -> None:
            gauge.value = value[0]

        def calculate_value() -> None:
            value[0] = psutil.cpu_percent(interval=1, percpu=False)
            Clock.schedule_once(set_value)

        Clock.schedule_interval(
            lambda _: Thread(target=calculate_value).start(),
            1,
        )

        return gauge

    @cached_property
    def ram_gauge(self: MenuApp) -> GaugeWidget:
        import psutil

        gauge = GaugeWidget(
            value=psutil.virtual_memory().percent,
            fill_color='#D68F24',
            label='RAM',
        )

        def set_value(_: int) -> None:
            gauge.value = psutil.virtual_memory().percent

        Clock.schedule_interval(set_value, 1)

        return gauge

    @cached_property
    def central(self: MenuApp) -> Widget:
        horizontal_layout = BoxLayout()

        self.menu_widget.size_hint = (None, 1)
        self.menu_widget.width = dp(SHORT_WIDTH)
        horizontal_layout.add_widget(self.menu_widget)

        central_column = BoxLayout(
            orientation='vertical',
            spacing=dp(12),
            padding=dp(16),
        )
        central_column.add_widget(self.cpu_gauge)
        central_column.add_widget(self.ram_gauge)
        central_column.size_hint = (1, 1)
        horizontal_layout.add_widget(central_column)

        right_column = BoxLayout(orientation='vertical')
        right_column.add_widget(VolumeWidget(value=40))
        right_column.size_hint = (None, 1)
        right_column.width = dp(SHORT_WIDTH)
        horizontal_layout.add_widget(right_column)

        def handle_depth_change(_: Widget, depth: int) -> None:
            if depth == 0:
                self.menu_widget.size_hint = (None, 1)
                self.menu_widget.width = dp(SHORT_WIDTH)
                central_column.size_hint = (1, 1)
                right_column.size_hint = (None, 1)
            else:
                self.menu_widget.size_hint = (1, 1)
                central_column.size_hint = (0, 1)
                right_column.size_hint = (0, 1)

        self.menu_widget.bind(depth=handle_depth_change)

        return horizontal_layout
---------------------

    def build(self: MenuApp) -> Widget | None:
        Window.bind(on_keyboard=self.on_keyboard)
        return super().build()

    def on_keyboard(
        self: MenuApp,
        _: WindowBase,
        key: int,
        _scancode: int,
        _codepoint: str,
        modifier: list[Modifier],
    ) -> None:
        """Handle keyboard events."""
        if modifier == []:
            if key == Keyboard.keycodes['up']:
                self.menu_widget.go_up()
            elif key == Keyboard.keycodes['down']:
                self.menu_widget.go_down()
            elif key == Keyboard.keycodes['1']:
                self.menu_widget.select(0)
            elif key == Keyboard.keycodes['2']:
                self.menu_widget.select(1)
            elif key == Keyboard.keycodes['3']:
                self.menu_widget.select(2)
            elif key == Keyboard.keycodes['left']:
                self.menu_widget.go_back()

    def on_button_event(
        self: MenuApp,
        button_pressed: ButtonName,
        button_status: ButtonStatus,
    ) -> None:
        if button_status == 'pressed':
            if button_pressed == ButtonName.UP:
                Clock.schedule_once(lambda _: self.menu_widget.go_up(), -1)
            elif button_pressed == ButtonName.DOWN:
                Clock.schedule_once(lambda _: self.menu_widget.go_down(), -1)
            elif button_pressed == ButtonName.TOP_LEFT:
                Clock.schedule_once(lambda _: self.menu_widget.select(0), -1)
            elif button_pressed == ButtonName.MIDDLE_LEFT:
                Clock.schedule_once(lambda _: self.menu_widget.select(1), -1)
            elif button_pressed == ButtonName.BOTTOM_LEFT:
                Clock.schedule_once(lambda _: self.menu_widget.select(2), -1)
            elif button_pressed == ButtonName.BACK:
                Clock.schedule_once(lambda _: self.menu_widget.go_back(), -1)
        self.root.reset_fps_control_queue()

threading.Timer(
    2,
    lambda: dispatch(
        [
            IconRegistrationAction(
                type='REGISTER_ICON',
                payload=IconRegistrationActionPayload(icon='wifi', priority=-1),
            )
            for _ in range(6)
        ],
    ),
).start()
