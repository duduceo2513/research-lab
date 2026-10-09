from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from accounts.models import User, UserRole


class UserSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(read_only=True)

    class Meta:
        model = User
        fields = ['id', 'email', 'username', 'first_name', 'last_name', 'full_name',
                  'role', 'is_active', 'is_staff', 'date_joined', 'last_login']
        read_only_fields = fields


class RegisterSerializer(serializers.ModelSerializer):
    """Public sign-up. Creates a TEACHER — the role that can use Research Lab; admins come from
    ``createsuperuser``."""

    password = serializers.CharField(write_only=True, style={'input_type': 'password'})

    class Meta:
        model = User
        fields = ['id', 'email', 'username', 'first_name', 'last_name', 'password']
        read_only_fields = ['id']
        extra_kwargs = {'username': {'required': False}}

    def validate_email(self, value):
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError('A user with this e-mail already exists.')
        return value.lower()

    def validate_password(self, value):
        validate_password(value)
        return value

    def create(self, validated_data):
        password = validated_data.pop('password')
        return User.objects.create_user(password=password, role=UserRole.TEACHER, **validated_data)


class MeUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'username']


class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True)

    def validate_old_password(self, value):
        if not self.context['request'].user.check_password(value):
            raise serializers.ValidationError('Wrong password.')
        return value

    def validate_new_password(self, value):
        validate_password(value, self.context['request'].user)
        return value
