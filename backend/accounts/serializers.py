from django.contrib.auth import get_user_model
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    role_display = serializers.CharField(source="get_role_display", read_only=True)
    module_display = serializers.CharField(source="get_module_display", read_only=True)
    is_admin = serializers.BooleanField(read_only=True)
    is_director = serializers.BooleanField(read_only=True)

    class Meta:
        model = User
        fields = (
            "id",
            "username",
            "first_name",
            "last_name",
            "email",
            "role",
            "role_display",
            "module",
            "module_display",
            "is_admin",
            "is_director",
            "is_active",
        )


class UserCreateSerializer(serializers.ModelSerializer):
    # required=False — чтобы при правке (PUT/PATCH) можно было не менять пароль.
    password = serializers.CharField(write_only=True, min_length=6, required=False)

    class Meta:
        model = User
        fields = (
            "id",
            "username",
            "first_name",
            "last_name",
            "email",
            "role",
            "module",
            "password",
        )

    def validate(self, attrs):
        # Направление обязательно для директора и игнорируется (очищается) у всех
        # остальных ролей — чтобы менеджер/админ случайно не оказались «привязаны».
        role = attrs.get("role", getattr(self.instance, "role", None))
        if role == User.Role.DIRECTOR:
            module = attrs.get("module", getattr(self.instance, "module", None))
            if not module:
                raise serializers.ValidationError(
                    {"module": "Укажите направление директора (Express или Business)."}
                )
        else:
            attrs["module"] = None
        return attrs

    def create(self, validated_data):
        password = validated_data.pop("password", None)
        user = User(**validated_data)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save()
        return user

    def update(self, instance, validated_data):
        # Пароль ДОЛЖЕН хешироваться и при правке — иначе DRF сохранит его
        # в открытом виде через setattr и заблокирует вход пользователю.
        password = validated_data.pop("password", None)
        user = super().update(instance, validated_data)
        if password:
            user.set_password(password)
            user.save(update_fields=["password"])
        return user


class LokoTokenObtainPairSerializer(TokenObtainPairSerializer):
    """JWT login that embeds the role and also returns the user object."""

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token["role"] = user.role
        token["username"] = user.username
        return token

    def validate(self, attrs):
        data = super().validate(attrs)
        data["user"] = UserSerializer(self.user).data
        return data
