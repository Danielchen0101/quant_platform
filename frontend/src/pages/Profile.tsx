import React, { useState } from 'react';
import { Card, Form, Input, Button, Avatar, Upload, message, Row, Col, Typography, Tag } from 'antd';
import { UserOutlined, MailOutlined, PhoneOutlined, EditOutlined, UploadOutlined } from '@ant-design/icons';

const { Title, Text } = Typography;

const Profile: React.FC = () => {
  const [editing, setEditing] = useState(false);
  const [form] = Form.useForm();

  const userData = {
    name: 'John Doe',
    email: 'john.doe@example.com',
    phone: '+1 (555) 123-4567',
    role: 'Premium Trader',
    joinDate: '2024-01-15',
    accountType: 'Professional',
    verification: 'Verified',
  };

  const onFinish = (values: any) => {
    console.log('Updated profile:', values);
    message.success('Profile updated successfully');
    setEditing(false);
  };

  const uploadProps = {
    name: 'avatar',
    action: 'https://www.mocky.io/v2/5cc8019d300000980a055e76',
    headers: {
      authorization: 'authorization-text',
    },
    onChange(info: any) {
      if (info.file.status !== 'uploading') {
        console.log(info.file, info.fileList);
      }
      if (info.file.status === 'done') {
        message.success(`${info.file.name} file uploaded successfully`);
      } else if (info.file.status === 'error') {
        message.error(`${info.file.name} file upload failed.`);
      }
    },
  };

  return (
    <div>
      <Row gutter={[16, 16]}>
        <Col xs={24} lg={8}>
          <Card>
            <div style={{ textAlign: 'center' }}>
              <Avatar
                size={120}
                icon={<UserOutlined />}
                style={{ marginBottom: 16 }}
              />
              <Title level={3} style={{ margin: '8px 0' }}>
                {userData.name}
              </Title>
              <Tag color="blue" style={{ marginBottom: 16 }}>
                {userData.role}
              </Tag>
              
              <Upload {...uploadProps}>
                <Button icon={<UploadOutlined />}>Change Avatar</Button>
              </Upload>
            </div>

            <div style={{ marginTop: 24 }}>
              <div style={{ marginBottom: 12 }}>
                <Text strong>Account Type:</Text>
                <Text style={{ float: 'right' }}>{userData.accountType}</Text>
              </div>
              <div style={{ marginBottom: 12 }}>
                <Text strong>Verification:</Text>
                <Tag color="green" style={{ float: 'right' }}>{userData.verification}</Tag>
              </div>
              <div style={{ marginBottom: 12 }}>
                <Text strong>Member Since:</Text>
                <Text style={{ float: 'right' }}>{userData.joinDate}</Text>
              </div>
            </div>
          </Card>
        </Col>

        <Col xs={24} lg={16}>
          <Card
            title="Profile Information"
            extra={
              <Button
                type={editing ? 'default' : 'primary'}
                icon={<EditOutlined />}
                onClick={() => {
                  if (editing) {
                    form.submit();
                  } else {
                    setEditing(true);
                  }
                }}
              >
                {editing ? 'Save Changes' : 'Edit Profile'}
              </Button>
            }
          >
            <Form
              form={form}
              layout="vertical"
              onFinish={onFinish}
              initialValues={userData}
              disabled={!editing}
            >
              <Row gutter={16}>
                <Col xs={24} md={12}>
                  <Form.Item
                    name="name"
                    label="Full Name"
                    rules={[{ required: true, message: 'Please input your name!' }]}
                  >
                    <Input
                      prefix={<UserOutlined />}
                      placeholder="Enter your name"
                    />
                  </Form.Item>
                </Col>
                <Col xs={24} md={12}>
                  <Form.Item
                    name="email"
                    label="Email Address"
                    rules={[
                      { required: true, message: 'Please input your email!' },
                      { type: 'email', message: 'Please enter a valid email!' },
                    ]}
                  >
                    <Input
                      prefix={<MailOutlined />}
                      placeholder="Enter your email"
                    />
                  </Form.Item>
                </Col>
              </Row>

              <Row gutter={16}>
                <Col xs={24} md={12}>
                  <Form.Item
                    name="phone"
                    label="Phone Number"
                  >
                    <Input
                      prefix={<PhoneOutlined />}
                      placeholder="Enter your phone number"
                    />
                  </Form.Item>
                </Col>
                <Col xs={24} md={12}>
                  <Form.Item
                    name="role"
                    label="Role"
                  >
                    <Input
                      prefix={<UserOutlined />}
                      placeholder="Enter your role"
                    />
                  </Form.Item>
                </Col>
              </Row>

              <Form.Item
                name="bio"
                label="Bio"
              >
                <Input.TextArea
                  rows={4}
                  placeholder="Tell us about yourself..."
                />
              </Form.Item>
            </Form>
          </Card>

          <Card title="Account Security" style={{ marginTop: 16 }}>
            <div style={{ marginBottom: 16 }}>
              <Text strong>Password</Text>
              <Button type="link" style={{ float: 'right' }}>
                Change Password
              </Button>
            </div>
            <div style={{ marginBottom: 16 }}>
              <Text strong>Two-Factor Authentication</Text>
              <Tag color="orange" style={{ float: 'right' }}>Not Enabled</Tag>
            </div>
            <div>
              <Text strong>Login History</Text>
              <Button type="link" style={{ float: 'right' }}>
                View History
              </Button>
            </div>
          </Card>
        </Col>
      </Row>
    </div>
  );
};

export default Profile;